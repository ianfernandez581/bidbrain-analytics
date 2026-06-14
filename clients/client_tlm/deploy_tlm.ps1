# One-shot stand-up: provisions everything needed for the TLM dashboard.
#
# Mirrors deploy_resetdata.ps1. Run this once to create the GCP resources, then
# use the three fast-path scripts for day-to-day deploys:
#   sql/deploy_views_tlm.ps1   — re-apply views only
#   job/deploy_job_tlm.ps1     — rebuild + redeploy the export job
#   dash/deploy_dash_tlm.ps1   — rebuild + redeploy the web app
#   scheduler.ps1               — wire the daily */10 timer (once)

$ErrorActionPreference = "Stop"

$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$CLIENT    = "tlm"
$DATASET   = "client_tlm"
$BUCKET    = "bidbrain-analytics-tlm-dash"
$REPO      = "bidbrain"

# --------------------------------------------------------------------
# 1. Enable APIs (idempotent)
# --------------------------------------------------------------------
Write-Host "--- Enabling APIs ---"
gcloud services enable cloudresourcemanager.googleapis.com artifactregistry.googleapis.com run.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com --project=$PROJECT

# --------------------------------------------------------------------
# 2. Artifact Registry repo (shared `bidbrain` — skip if exists)
# --------------------------------------------------------------------
Write-Host "--- Artifact Registry ---"
$exists = gcloud artifacts repositories describe $REPO --location=$REGION --project=$PROJECT 2>$null
if (-not $exists) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION --project=$PROJECT
}

# --------------------------------------------------------------------
# 3. GCS bucket (private data store for tlm.json)
# --------------------------------------------------------------------
Write-Host "--- GCS bucket ---"
$b = gcloud storage buckets describe gs://$BUCKET --project=$PROJECT 2>$null
if (-not $b) {
  gcloud storage buckets create gs://$BUCKET --location=$REGION --public-access-prevention=enforced --project=$PROJECT
}

# --------------------------------------------------------------------
# 4. BigQuery dataset
# --------------------------------------------------------------------
Write-Host "--- BigQuery dataset ---"
$ds = bq show --project_id=$PROJECT $DATASET 2>$null
if (-not $ds) {
  bq mk --project_id=$PROJECT --location=$REGION $DATASET
}

# --------------------------------------------------------------------
# 5. Service accounts
# --------------------------------------------------------------------
Write-Host "--- Service accounts ---"
$jobSA = "tlm-dash-job@$PROJECT.iam.gserviceaccount.com"
$webSA = "tlm-dash-web@$PROJECT.iam.gserviceaccount.com"

$sa = gcloud iam service-accounts describe $jobSA --project=$PROJECT 2>$null
if (-not $sa) {
  gcloud iam service-accounts create tlm-dash-job --display-name="TLM export job" --project=$PROJECT
}
$sa = gcloud iam service-accounts describe $webSA --project=$PROJECT 2>$null
if (-not $sa) {
  gcloud iam service-accounts create tlm-dash-web --display-name="TLM dash web app" --project=$PROJECT
}

# --------------------------------------------------------------------
# 6. IAM: job SA = bigquery.dataViewer (project-scoped — covers both
#    raw_google_ads + raw_windsor) + jobUser + bucket objectAdmin
# --------------------------------------------------------------------
Write-Host "--- IAM ---"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$jobSA" --role=roles/bigquery.dataViewer --condition=None 2>$null
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$jobSA" --role=roles/bigquery.jobUser --condition=None 2>$null
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member="serviceAccount:$jobSA" --role=roles/storage.objectAdmin --project=$PROJECT 2>$null

# web SA = bucket objectViewer + secret accessor
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member="serviceAccount:$webSA" --role=roles/storage.objectViewer --project=$PROJECT 2>$null
gcloud secrets add-iam-policy-binding tlm-dash-password --member="serviceAccount:$webSA" --role=roles/secretmanager.secretAccessor --project=$PROJECT 2>$null
gcloud secrets add-iam-policy-binding tlm-dash-session-key --member="serviceAccount:$webSA" --role=roles/secretmanager.secretAccessor --project=$PROJECT 2>$null

# Also let the Cloud Build trigger's SA act as the runtime SAs
$cbSA = "serviceAccount:$(gcloud projects describe $PROJECT --format='value(projectNumber)')"+"@cloudbuild.gserviceaccount.com"
gcloud iam service-accounts add-iam-policy-binding $jobSA --member="$cbSA" --role=roles/iam.serviceAccountUser --project=$PROJECT 2>$null
gcloud iam service-accounts add-iam-policy-binding $webSA --member="$cbSA" --role=roles/iam.serviceAccountUser --project=$PROJECT 2>$null

# --------------------------------------------------------------------
# 7. Secrets (create once; manual value entry in Console)
# --------------------------------------------------------------------
Write-Host "--- Secrets ---"
$sp = gcloud secrets describe tlm-dash-password --project=$PROJECT 2>$null
if (-not $sp) { gcloud secrets create tlm-dash-password --project=$PROJECT --replication-policy=automatic }
$sp = gcloud secrets describe tlm-dash-session-key --project=$PROJECT 2>$null
if (-not $sp) { gcloud secrets create tlm-dash-session-key --project=$PROJECT --replication-policy=automatic }

# --------------------------------------------------------------------
# 8. Apply BigQuery views
# --------------------------------------------------------------------
Write-Host "--- Applying views ---"
python client_tlm/create_views.py

# --------------------------------------------------------------------
# 9. Deploy export job + dash
# --------------------------------------------------------------------
Write-Host "--- Build & deploy export job ---"
& "$PSScriptRoot/job/deploy_job_tlm.ps1"

Write-Host "--- Build & deploy web app ---"
& "$PSScriptRoot/dash/deploy_dash_tlm.ps1"

# --------------------------------------------------------------------
# 10. Run first export
# --------------------------------------------------------------------
Write-Host "--- First export ---"
gcloud run jobs execute tlm-export --region=$REGION --project=$PROJECT --wait

# --------------------------------------------------------------------
# 11. Wire the daily scheduler (one-time)
# --------------------------------------------------------------------
Write-Host "--- Scheduler ---"
& "$PSScriptRoot/scheduler.ps1"

Write-Host "`nTLM dashboard stand-up complete."
Write-Host "  Dashboard: gcloud run services describe tlm-dash --region=$REGION --format='value(status.url)'"