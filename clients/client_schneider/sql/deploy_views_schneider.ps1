# deploy_views_schneider.ps1 - (re)load the seed CSVs then reapply the schneider SQL views then
# re-run the export JOB after editing sql/*.sql (or data/*.csv). FIRST loads data/*.csv into the
# seed_* TABLES via load_seeds.py (the new stg_salesforce / lead_* views read seed_salesforce_map,
# so the table must exist before the views are applied), THEN applies every sql/*.sql via
# create_views.py (the source-of-truth applier - NEVER edit views in the BigQuery console or they
# drift), THEN runs schneider-export so schneider.json reflects the new output. Does NOT rebuild any
# image or redeploy the service.
#
# Needs the repo venv (load_seeds.py + create_views.py use the BigQuery client). Run the one-shot
# deploy_schneider.ps1 once first if the dataset/job don't exist yet.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_schneider\sql\deploy_views_schneider.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches deploy_schneider.ps1) ----------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "schneider-export"
$REPO_ROOT = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent  # sql -> client_schneider -> clients -> repo root
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$CLIENT_DIR= Split-Path $PSScriptRoot -Parent
$LOAD_PY   = Join-Path $CLIENT_DIR "load_seeds.py"
$VIEWS_PY  = Join-Path $CLIENT_DIR "create_views.py"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Test-Path $PYTHON))   { Die "repo venv python not found at $PYTHON" }
if (-not (Test-Path $LOAD_PY))  { Die "load_seeds.py not found at $LOAD_PY" }
if (-not (Test-Path $VIEWS_PY)) { Die "create_views.py not found at $VIEWS_PY" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Loading data/*.csv into the seed_* tables via load_seeds.py (must precede the views) ..."
& $PYTHON $LOAD_PY; Must "load seeds"
Write-Host "Reapplying SQL views via create_views.py ..."
& $PYTHON $VIEWS_PY; Must "apply views"
Write-Host "Re-running $JOB so schneider.json reflects the new views ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run job"

Write-Host "`nDONE. Views reapplied and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
