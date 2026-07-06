# deploy_job_status.ps1 - rebuild + redeploy + run ONLY the status-export JOB after editing
# job/main.py (the CLIENTS spec / accuracy queries / verdict logic) or job/requirements.txt.
# Rebuilds the job image, deploys it to the status-export Cloud Run job (re-binding the Snowflake
# key secret), then runs it once so a fresh status.json lands in the bucket.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\status_dashboard\job\deploy_job_status.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$JOB      = "status-export"
$JOB_SA   = "status-dash-job@${PROJECT}.iam.gserviceaccount.com"
$SF_SECRET= "snowflake-bq-key"                          # EXISTING shared Snowflake key
$JOB_DIR  = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
Write-Host "Rebuilding $JOB image ($SHA) ..."
gcloud builds submit $JOB_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build job image"
Write-Host "Deploying Cloud Run job $JOB ..."
gcloud run jobs deploy $JOB --image $IMG --region $REGION --service-account $JOB_SA --memory 1Gi `
  --set-secrets "SNOWFLAKE_KEY=${SF_SECRET}:latest" --project $PROJECT; Must "deploy job"

# --- IAM the job needs to VERIFY the BigQuery-native clients (100% Digital agency) ------------
# The BQ_CLIENTS accuracy checks read the raw BQ layer (raw_windsor / raw_neto / raw_ga4 /
# raw_google_ads) directly and read each client's <c>.json from its bucket. These grants are
# idempotent (add = no-op if present) so it's safe to re-run. Least-privilege = read-only.
Write-Host "Granting the status SA read on the raw BQ layer + the 100% Digital client buckets ..."
gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$JOB_SA" `
  --role roles/bigquery.jobUser   --condition=None --quiet | Out-Null
gcloud projects add-iam-policy-binding $PROJECT --member "serviceAccount:$JOB_SA" `
  --role roles/bigquery.dataViewer --condition=None --quiet | Out-Null
foreach ($c in @("cityperfume","resetdata","tlm","geocon","vmch")) {
  gcloud storage buckets add-iam-policy-binding "gs://bidbrain-analytics-$c-dash" `
    --member "serviceAccount:$JOB_SA" --role roles/storage.objectViewer --quiet | Out-Null
}

Write-Host "Running $JOB (writes a fresh status.json to the bucket) ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run job"

Write-Host "`nDONE. $JOB rebuilt, deployed, and executed. The dash service serves the new status.json immediately."
