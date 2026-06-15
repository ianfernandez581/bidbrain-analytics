# deploy_job_cloudflare.ps1 - rebuild + redeploy + run ONLY the cloudflare export JOB after editing
# job/main.py (the JSON shape the dashboard reads) or job/requirements.txt. Rebuilds the job image,
# deploys it to the cloudflare-export Cloud Run job, then runs it once so a fresh cloudflare.json
# lands in the bucket. Does NOT touch the dash service, SQL views, or IAM.
#
# Use this when you changed which fields the job emits / how it assembles cloudflare.json.
# If you ALSO edited a sql/*.sql view that feeds it, run deploy_views_cloudflare.ps1 first (it
# reapplies the views) - then this rebuild re-reads the current views.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_cloudflare\job\deploy_job_cloudflare.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches job/cloudbuild.yaml) -----------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                 # Artifact Registry docker repo (shared)
$JOB      = "cloudflare-export"
$JOB_SA   = "cloudflare-dash-job@${PROJECT}.iam.gserviceaccount.com"
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
gcloud run jobs deploy $JOB --image $IMG --region $REGION --service-account $JOB_SA --memory 1Gi --project $PROJECT; Must "deploy job"
Write-Host "Running $JOB (writes a fresh cloudflare.json to the bucket) ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run job"

Write-Host "`nDONE. $JOB rebuilt, deployed, and executed. The dash service serves the new JSON immediately (no service redeploy needed)."
