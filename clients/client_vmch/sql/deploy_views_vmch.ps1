# deploy_views_vmch.ps1 - reapply the VMCH SQL views then refresh vmch.json after editing sql/*.sql.
# Applies every sql/*.sql via create_views.py (the source-of-truth applier - NEVER edit views in the
# BigQuery console or they drift; create_views.py also avoids the Windows `Get-Content | bq query`
# UTF-8 comment-corruption gotcha), then re-runs vmch-export so vmch.json reflects the new view output.
#
# A view-only edit does NOT advance any raw-table watermark, so the export's freshness gate would
# otherwise SKIP the rebuild and the JSON would silently go stale. We clear the watermark sidecar
# first to force exactly ONE rebuild; the job rewrites the watermark, so later */10 ticks behave
# normally. No image rebuild / no service redeploy - views + JSON only.
#
# Needs the repo venv (create_views.py uses the BigQuery client). Run deploy_vmch.ps1 once first if
# the dataset/job don't exist yet.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\clients\client_vmch\sql\deploy_views_vmch.ps1

$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$JOB       = "vmch-export"
$BUCKET    = "bidbrain-analytics-vmch-dash"
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

# View-only edits don't advance any raw watermark -> clear it so the gated job rebuilds exactly once.
Write-Host "Clearing freshness watermark to force one rebuild ..."
gcloud storage rm "gs://$BUCKET/_freshness.json" --project $PROJECT 2>$null

Write-Host "Re-running $JOB so vmch.json reflects the new views ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run job"

Write-Host "`nDONE. Views reapplied and $JOB re-run. The dash service serves the new JSON immediately (no image rebuild, no service redeploy)."
