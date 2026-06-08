# deploy_job_cityperfume.ps1 - rebuild + redeploy + run ONLY the cityperfume export JOB after
# editing job/main.py (the JSON shape the dashboard reads) or job/requirements.txt. Rebuilds the
# job image, deploys it to the cityperfume-export Cloud Run job, then runs it once so a fresh
# cityperfume.json lands in the private bucket. Does NOT touch the dash service, SQL views, or IAM.
#
# Use this when you changed which fields the job emits / how it assembles cityperfume.json.
# If you ALSO edited a sql/*.sql view that feeds it, run ..\sql\deploy_views_cityperfume.ps1 first
# (it reapplies the views) - then this rebuild re-reads the current views.
# For first-time standup use the one-shot ..\deploy_cityperfume.ps1.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_cityperfume\job\deploy_job_cityperfume.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches deploy_cityperfume.ps1 + job/cloudbuild.yaml) ----------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                          # Artifact Registry docker repo (shared)
$JOB      = "cityperfume-export"
$JOB_SA   = "cityperfume-dash-job@${PROJECT}.iam.gserviceaccount.com"
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
Write-Host "Running $JOB (writes a fresh cityperfume.json to the bucket) ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run job"

Write-Host "`nDONE. $JOB rebuilt, deployed, and executed. The dash service serves the new JSON immediately (no service redeploy needed)."
