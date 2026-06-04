# deploy_views_mongodb.ps1 - reapply the mongodb SQL views then re-run the export JOB after editing
# sql/*.sql. Applies every sql/*.sql via create_views.py (the source-of-truth applier - NEVER edit
# views in the BigQuery console or they drift), then runs mongodb-export so mongodb.json reflects
# the new view output. Does NOT rebuild any image or redeploy the service - views + JSON only.
#
# Needs the repo venv (create_views.py uses the BigQuery client). The dataset/job must already
# exist (mongodb is the template client and is already stood up).
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_mongodb\deploy_views_mongodb.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config -----------------------------------------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "mongodb-export"
$REPO_ROOT = Split-Path $PSScriptRoot -Parent
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$VIEWS_PY  = Join-Path $PSScriptRoot "create_views.py"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Test-Path $PYTHON))   { Die "repo venv python not found at $PYTHON" }
if (-not (Test-Path $VIEWS_PY)) { Die "create_views.py not found at $VIEWS_PY" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Reapplying SQL views via create_views.py ..."
& $PYTHON $VIEWS_PY; Must "apply views"
Write-Host "Re-running $JOB so mongodb.json reflects the new views ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run job"

Write-Host "`nDONE. Views reapplied and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
