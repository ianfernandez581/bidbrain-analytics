# deploy_views_schneidersecpwr.ps1 - reapply the schneidersecpwr SQL views then re-run the export JOB
# after editing sql/*.sql. Applies every sql/*.sql via create_views.py (the source-of-truth applier -
# NEVER edit views in the BigQuery console or they drift), THEN runs schneidersecpwr-export with
# FORCE_REBUILD=1 so schneidersecpwr.json reflects the new output. Does NOT rebuild any image or
# redeploy the service.
#
# There is no TARGET seed (unlike client_schneiderlqai / client_schneider): these three campaigns are
# DELIVERY-ONLY - no media plan, no targets. If a signed media plan ever lands, add
# data/media_plan.csv + load_seeds.py the repo-standard way and call it BEFORE create_views.py here.
#
# There IS one seed, loaded first below: targeting/adset_targeting.csv -> seed_adset_targeting, the
# hand-recorded LinkedIn ad-set audience behind the Reports tab. sql/05_linkedin_adsets LEFT JOINs
# it, so the load must precede create_views.py or that view cannot be created. Editing the CSV alone
# also needs this script (the freshness gate does not watch seed tables - repo AGENTS.md).
#
# Needs the repo venv (create_views.py uses the BigQuery client). Run the one-shot
# deploy_schneidersecpwr.ps1 once first if the dataset/job don't exist yet.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\clients\client_schneidersecpwr\sql\deploy_views_schneidersecpwr.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches deploy_schneidersecpwr.ps1) ----------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "schneidersecpwr-export"
$REPO_ROOT = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent  # sql -> client_schneidersecpwr -> clients -> repo root
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$CLIENT_DIR= Split-Path $PSScriptRoot -Parent
$VIEWS_PY  = Join-Path $CLIENT_DIR "create_views.py"
$SEED_PY   = Join-Path $CLIENT_DIR "load_targeting.py"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Test-Path $PYTHON))   { Die "repo venv python not found at $PYTHON" }
if (-not (Test-Path $VIEWS_PY)) { Die "create_views.py not found at $VIEWS_PY" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Loading targeting/adset_targeting.csv -> seed_adset_targeting (sql/05 joins it) ..."
& $PYTHON $SEED_PY; Must "load targeting seed"
Write-Host "Reapplying SQL views via create_views.py ..."
& $PYTHON $VIEWS_PY; Must "apply views"
Write-Host "Re-running $JOB so schneidersecpwr.json reflects the new views ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run job"

Write-Host "`nDONE. Views reapplied and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
