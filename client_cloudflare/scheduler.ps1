<#
  scheduler.ps1  (Cloudflare)
  Creates/refreshes a daily Cloud Scheduler trigger that runs the
  'cloudflare-export' Cloud Run Job at 22:00 UTC. Idempotent -- safe to re-run.
  Run from anywhere:  .\client_cloudflare\scheduler.ps1
#>
$ErrorActionPreference = "Stop"

$Project  = "bidbrain-analytics"
$Region   = "australia-southeast1"
$Job      = "cloudflare-export"
$Sa       = "cloudflare-dash-job@bidbrain-analytics.iam.gserviceaccount.com"
$Cron     = "0 22 * * *"
$TimeZone = "UTC"
$Sched    = "$Job-daily"

Write-Host "==> Ensuring Cloud Scheduler API is enabled..."
gcloud services enable cloudscheduler.googleapis.com --project $Project | Out-Null

Write-Host "==> Granting $Sa permission to run the job (run.invoker)..."
gcloud run jobs add-iam-policy-binding $Job `
  --region $Region --project $Project `
  --member "serviceAccount:$Sa" `
  --role roles/run.invoker | Out-Null

$Uri = "https://$Region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$Project/jobs/${Job}:run"

gcloud scheduler jobs describe $Sched --location $Region --project $Project 2>$null | Out-Null
$Exists = ($LASTEXITCODE -eq 0)

if ($Exists) {
  Write-Host "==> Updating existing scheduler job '$Sched'..."
  gcloud scheduler jobs update http $Sched `
    --location $Region --project $Project `
    --schedule $Cron --time-zone $TimeZone `
    --uri $Uri --http-method POST `
    --oauth-service-account-email $Sa
} else {
  Write-Host "==> Creating scheduler job '$Sched'..."
  gcloud scheduler jobs create http $Sched `
    --location $Region --project $Project `
    --schedule $Cron --time-zone $TimeZone `
    --uri $Uri --http-method POST `
    --oauth-service-account-email $Sa
}

Write-Host ""
Write-Host "Done. '$Sched' runs '$Job' daily at '$Cron' ($TimeZone)."
Write-Host "Test now:  gcloud scheduler jobs run $Sched --location $Region --project $Project"