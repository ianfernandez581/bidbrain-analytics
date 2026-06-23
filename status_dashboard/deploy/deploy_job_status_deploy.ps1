# deploy_job_status_deploy.ps1 - one-shot, idempotent stand-up of the status-deploy Cloud Run JOB
# (the privileged "Make this live" worker triggered by the platform front-door's Data Accuracy tab).
#
# Creates the status-deploy@ service account, grants it the LEAST privilege it needs (dataset-level
# WRITER on each client dataset, project bigquery.jobUser, objectAdmin on the status bucket, and
# run.invoker on the <c>-export + status-export jobs), lets the platform web SA trigger this job,
# then builds + deploys the job. Re-run after editing deploy/main.py or to onboard a new client dataset.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\status_dashboard\deploy\deploy_job_status_deploy.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config -----------------------------------------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$REPO      = "bidbrain"
$JOB       = "status-deploy"
$JOB_SA    = "status-deploy@${PROJECT}.iam.gserviceaccount.com"
$PLAT_SA   = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"   # triggers this job from the UI
$BUCKET    = "bidbrain-analytics-status-dash"                         # holds definitions/<c>.json
$JOB_DIR   = $PSScriptRoot
$REPO_ROOT = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent    # deploy -> status_dashboard -> repo root
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$GRANT_PY  = Join-Path $JOB_DIR "grant_dataset_writer.py"

# Client datasets this worker may seed, and the export jobs it may RUN. Add a line per client on rollout.
$CLIENT_DATASETS = @("client_cloudflare")
$EXPORT_JOBS     = @("cloudflare-export", "status-export")

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path $PYTHON)) { Die "repo venv python not found at $PYTHON" }

Write-Host "Standing up the status-deploy job in $PROJECT ($REGION)`n"

# ---- 1. Service account -----------------------------------------------------
Write-Host "[1/5] Service account ..."
if (-not (Exists { gcloud iam service-accounts describe $JOB_SA --project $PROJECT })) {
  gcloud iam service-accounts create "status-deploy" --display-name "Status 'Make this live' deploy worker" --project $PROJECT; Must "create SA"
}

# ---- 2. IAM (least privilege) -----------------------------------------------
Write-Host "[2/5] IAM ..."
# Run query + load jobs (project-level jobUser; the WRITE itself is gated per-dataset below).
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser" --condition=None | Out-Null; Must "grant jobUser"
# Read staged/live definitions + write live + delete staged.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin" | Out-Null; Must "grant objectAdmin (status bucket)"
# Dataset-level WRITER on each client dataset (NOT project-wide dataEditor — keep the blast radius small).
foreach ($d in $CLIENT_DATASETS) {
  & $PYTHON $GRANT_PY $d $JOB_SA; Must "grant WRITER on $d"
}

# ---- 3. run.invoker so this job may RUN the export jobs (RUN != deploy, so no actAs needed) ----
Write-Host "[3/5] run.invoker on the export jobs ..."
foreach ($j in $EXPORT_JOBS) {
  gcloud run jobs add-iam-policy-binding $j --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
}

# ---- 4. Build + deploy ------------------------------------------------------
Write-Host "[4/5] Build + deploy the status-deploy job ..."
$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()
$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
gcloud builds submit $JOB_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build job image"
gcloud run jobs deploy $JOB --image $IMG --region $REGION --service-account $JOB_SA --memory 512Mi --project $PROJECT; Must "deploy job"

# ---- 5. Wire the platform front-door to the status pipeline -----------------
# The platform reads status.json (health + accuracy), reads/writes definitions/<c>(.staged).json,
# appends the audit log, and TRIGGERS this job. So it needs objectAdmin on the status bucket +
# run.invoker on this job. (The platform SA is already god-mode-trusted — it rotates every
# dashboard password — so objectAdmin on this one bucket is consistent with its trust level.)
Write-Host "[5/5] Allow the platform front-door to read status + stage definitions + trigger status-deploy ..."
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${PLAT_SA}" --role="roles/run.invoker" *> $null
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${PLAT_SA}" --role="roles/storage.objectAdmin" | Out-Null; Must "grant platform objectAdmin on status bucket"

Write-Host "`nDONE. status-deploy is deployed and the platform can read status.json, stage edits, and"
Write-Host "trigger it (DEPLOY_CLIENT=<c> -> seed + smoke-check + promote + rerun the exports)."
