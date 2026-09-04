# deploy_job_connections.ps1 - build, deploy and schedule the windsor-connections-probe Cloud Run job.
#
# What it stands up (idempotent - safe to re-run):
#   * image  australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/windsor-connections-probe:<sha>
#   * job    windsor-connections-probe, SA ingest-runner@ (the same SA the Windsor loaders run as,
#            which already reads the windsor-api-key secret and BigQuery), plus:
#              - roles/storage.objectAdmin on gs://bidbrain-analytics-status-dash (writes windsor_connections.json)
#              - roles/secretmanager.secretAccessor on windsor-alerts-gmail-oauth (the Gmail SEND token; optional -
#                without it the job still runs, logs the alerts it would have sent, and the tab says "Email alerts off")
#   * scheduler  windsor-connections-probe-hourly, cron "7 * * * *" UTC
#   * -Run       execute once now so the Grid's Connections tab fills in immediately
#
# Usage (from the repo root, WinPS 5.1, config pinned by the VS Code window):
#   .\ingest\windsor_data_pull\connections\deploy_job_connections.ps1 -Run
#   .\ingest\windsor_data_pull\connections\deploy_job_connections.ps1 -SkipBuild     # reschedule / re-grant only
param([switch]$Run, [switch]$SkipBuild, [string]$Cron = "7 * * * *")

$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"
$PNUM    = "516554645957"
$REGION  = "australia-southeast1"
$REPO    = "bidbrain"
$JOB     = "windsor-connections-probe"
$SA      = "ingest-runner@$PROJECT.iam.gserviceaccount.com"
$BUCKET  = "bidbrain-analytics-status-dash"
$GMAIL_SECRET   = "windsor-alerts-gmail-oauth"
$WINDSOR_SECRET = "windsor-api-key"
$DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

function Must($what) { if ($LASTEXITCODE -ne 0) { throw "FAILED: $what" } }

$SHA = (git rev-parse --short HEAD 2>$null); if (-not $SHA) { $SHA = "manual-" + (Get-Date -Format yyyyMMddHHmm) }
$IMG = "$REGION-docker.pkg.dev/$PROJECT/$REPO/${JOB}:$SHA"

if (-not $SkipBuild) {
  Write-Host "[probe] Building $IMG ..."
  gcloud builds submit $DIR --tag $IMG --region $REGION --project $PROJECT; Must "build image"
  Write-Host "[probe] Deploying Cloud Run job $JOB ..."
  gcloud run jobs deploy $JOB --image $IMG --region $REGION --project $PROJECT --service-account $SA `
    --memory 1Gi --cpu 1 --task-timeout 1200 --max-retries 0 `
    --set-env-vars "CONNECTIONS_BUCKET=$BUCKET,GMAIL_TOKEN_SECRET=$GMAIL_SECRET,WINDSOR_SECRET=$WINDSOR_SECRET" `
    --quiet; Must "deploy job"
}

Write-Host "[probe] Granting $SA what the probe reads and writes (idempotent) ..."
gcloud secrets add-iam-policy-binding $WINDSOR_SECRET --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null
gcloud secrets describe $GMAIL_SECRET --project $PROJECT *> $null
if ($LASTEXITCODE -eq 0) {
  gcloud secrets add-iam-policy-binding $GMAIL_SECRET --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null
} else {
  Write-Host "[probe] NOTE: secret $GMAIL_SECRET does not exist yet - alerts will be LOGGED, not emailed."
  Write-Host "        Mint it with ingest\windsor_data_pull\connections\gen_gmail_token.py (see its header), then re-run this script with -SkipBuild."
}
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectAdmin" --project $PROJECT *> $null
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.jobUser" --condition=None --quiet *> $null
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer" --condition=None --quiet *> $null

Write-Host "[probe] Scheduling '$Cron' UTC ..."
$SCHED_SA = "service-$PNUM@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:$SA" --role="roles/run.invoker" *> $null
$uri = "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/${JOB}:run"
gcloud scheduler jobs describe "$JOB-hourly" --location $REGION --project $PROJECT *> $null
if ($LASTEXITCODE -eq 0) {
  gcloud scheduler jobs update http "$JOB-hourly" --location $REGION --project $PROJECT --schedule="$Cron" --time-zone="UTC"; Must "update scheduler"
} else {
  gcloud scheduler jobs create http "$JOB-hourly" --location $REGION --project $PROJECT `
    --schedule="$Cron" --time-zone="UTC" --uri="$uri" --http-method=POST --oauth-service-account-email="$SA"; Must "create scheduler"
}

# The Grid's runtime SA must be able to start the job from the tab's "Probe now" button. deploy_grid.ps1
# asserts the same binding, but the job has to exist first - so assert it here too.
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT `
  --member="serviceAccount:$PNUM-compute@developer.gserviceaccount.com" --role="roles/run.invoker" *> $null

if ($Run) {
  Write-Host "[probe] Executing $JOB once (writes gs://$BUCKET/windsor_connections.json) ..."
  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "execute job"
}
Write-Host "[probe] Done. The Grid -> Connections tab reads gs://$BUCKET/windsor_connections.json (hourly)."
