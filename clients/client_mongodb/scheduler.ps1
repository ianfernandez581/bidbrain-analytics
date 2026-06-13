<#
  scheduler.ps1  (MongoDB)
  Creates/refreshes a Cloud Scheduler trigger that runs the 'mongodb-export'
  Cloud Run Job on a frequent cadence (default */10 min). The job is SELF-GATING:
  each tick it cheaply checks (via BQ __TABLES__.last_modified) whether its upstream
  raw_snowflake tables advanced and only rebuilds when they did, so most ticks are a
  ~3s no-op. Net effect: the dashboard refreshes within ~10 min of new data.
  Idempotent -- safe to re-run. Pass -Cron to override the cadence.
  Run from anywhere:  .\client_mongodb\scheduler.ps1
#>
param([string]$Cron = "*/10 * * * *")
# Deliberately NOT ErrorActionPreference="Stop": gcloud writes progress to stderr, which
# PowerShell 5.1 wraps as a NativeCommandError -> under Stop that throws mid-script (even
# though gcloud succeeded), aborting before the scheduler update. The other clients' scripts
# omit it for the same reason.

$Project  = "bidbrain-analytics"
$Region   = "australia-southeast1"
$Job      = "mongodb-export"
$Sa       = "mongodb-dash-job@bidbrain-analytics.iam.gserviceaccount.com"
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
Write-Host "Done. '$Sched' triggers '$Job' on '$Cron' ($TimeZone)."
Write-Host "The job self-gates: most ticks no-op in ~3s; it rebuilds within ~10 min of new upstream data."
Write-Host "Test now:  gcloud scheduler jobs run $Sched --location $Region --project $Project"