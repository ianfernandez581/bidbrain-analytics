# deploy_seeds_schneiderlqai.ps1 - reload the human-editable seed CSVs in data/ into the BigQuery
# seed_* TABLES, then re-run the export JOB so schneiderlqai.json reflects them. Use this after editing
# anything under clients/client_schneiderlqai/data/ (campaign_map / plan_budget / media_plan /
# salesforce_map / targets / channel_split / plan_flighting).
#
# The seeds are TABLES loaded from CSV (not views), and they are NOT an upstream the freshness gate
# watches, so the job is re-run with FORCE_REBUILD=1 (a seed edit would otherwise be a silent no-op).
# load_seeds.py auto-migrates any pre-existing seed_* VIEW (from the old sql/30-34) to a table on the
# first run, so this is safe to run repeatedly.
#
# If you ALSO edited a sql/*.sql view, run sql/deploy_views_schneiderlqai.ps1 instead (it loads the seeds
# AND reapplies the views before re-running the job). For first-time standup use deploy_schneiderlqai.ps1.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_schneiderlqai\deploy_seeds_schneiderlqai.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (matches deploy_schneiderlqai.ps1) ----------------------------------
$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "schneiderlqai-export"
$REPO_ROOT = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent   # client_schneiderlqai -> clients -> repo root
$PYTHON    = Join-Path $REPO_ROOT ".venv\Scripts\python.exe"
$LOAD_PY   = Join-Path $PSScriptRoot "load_seeds.py"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Test-Path $PYTHON))  { Die "repo venv python not found at $PYTHON" }
if (-not (Test-Path $LOAD_PY)) { Die "load_seeds.py not found at $LOAD_PY" }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Loading data/*.csv into the client_schneiderlqai seed_* tables via load_seeds.py ..."
& $PYTHON $LOAD_PY; Must "load seeds"
Write-Host "Re-running $JOB (FORCE_REBUILD=1) so schneiderlqai.json reflects the new seeds ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run job"

Write-Host "`nDONE. Seeds reloaded and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
