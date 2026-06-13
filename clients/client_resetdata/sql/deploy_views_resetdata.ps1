# deploy_views_resetdata.ps1 - reapply the resetdata SQL views then re-run the export JOB after
# editing sql/*.sql. Applies every sql/*.sql via create_views.py (the source-of-truth applier -
# NEVER edit views in the BigQuery console or they drift), then runs resetdata-export so
# resetdata.json reflects the new view output. Does NOT rebuild any image or redeploy the service.
#
# Needs the repo venv (create_views.py uses the BigQuery client). Run the one-shot deploy_resetdata.ps1
# once first if the dataset/job don't exist yet.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_resetdata\sql\deploy_views_resetdata.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches deploy_resetdata.ps1) ----------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "resetdata-export"
$REPO_ROOT = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$VIEWS_PY  = Join-Path (Split-Path $PSScriptRoot -Parent) "create_views.py"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Test-Path $PYTHON))   { Die "repo venv python not found at $PYTHON" }
if (-not (Test-Path $VIEWS_PY)) { Die "create_views.py not found at $VIEWS_PY" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Reapplying SQL views via create_views.py ..."
& $PYTHON $VIEWS_PY; Must "apply views"
Write-Host "Re-running $JOB so resetdata.json reflects the new views ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run job"

Write-Host "`nDONE. Views reapplied and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
