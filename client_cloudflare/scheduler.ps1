<#
  scheduler.ps1  (Cloudflare)
  Creates/refreshes a Cloud Scheduler trigger that runs the 'cloudflare-export'
  Cloud Run Job on a frequent cadence (default */10 min). The job is SELF-GATING:
  each tick it cheaply probes whether its upstream Snowflake tables have new data
  and only rebuilds when they do, so most ticks are a ~3s no-op. The net effect is
  the dashboard refreshes within ~10 min of new data instead of once a day.
  Idempotent -- safe to re-run. Pass -Cron to override the cadence.
  Run from anywhere:  .\client_cloudflare\scheduler.ps1
#>
param([string]$Cron = "*/10 * * * *")
# Deliberately NOT ErrorActionPreference="Stop": gcloud writes progress to stderr, which
# PowerShell 5.1 wraps as a NativeCommandError -> under Stop that throws mid-script (even
# though gcloud succeeded), aborting before the scheduler update. The other clients' scripts
# omit it for the same reason.

$Project  = "bidbrain-analytics"
$Region   = "australia-southeast1"
$Job      = "cloudflare-export"
$Sa       = "cloudflare-dash-job@bidbrain-analytics.iam.gserviceaccount.com"
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
Write-Host "Done. '$Sched' triggers '$Job' on '$Cron' ($TimeZone) -> POST $Uri"
Write-Host "The job self-gates: most ticks no-op in ~3s; it rebuilds within ~10 min of new Snowflake data."
Write-Host "Test now:  gcloud scheduler jobs run $Sched --location $Region --project $Project"