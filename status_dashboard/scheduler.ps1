<#
  scheduler.ps1  (status / meta dashboard)
  Creates/refreshes a Cloud Scheduler trigger that runs 'status-export' on a frequent
  cadence (default */15 min). The job is CHEAP per tick: the Snowflake LAST_ALTERED
  freshness probe is metadata-only (never resumes the warehouse), and the accuracy
  COUNT/SUM queries self-gate -- they only re-run for a client whose Snowflake source
  advanced since the last status.json. Idempotent -- safe to re-run. Pass -Cron to override.
  Run from anywhere:  .\status_dashboard\scheduler.ps1
#>
param([string]$Cron = "*/15 * * * *")
$ErrorActionPreference = "Stop"

$Project  = "bidbrain-analytics"
$Region   = "australia-southeast1"
$Job      = "status-export"
$Sa       = "status-dash-job@bidbrain-analytics.iam.gserviceaccount.com"
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
Write-Host "Idle ticks are metadata-only (free); accuracy counts resume the warehouse only when a source advanced."
Write-Host "Test now:  gcloud scheduler jobs run $Sched --location $Region --project $Project"
