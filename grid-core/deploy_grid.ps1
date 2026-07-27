# deploy_grid.ps1 - redeploy The Grid (the `central-grid` Cloud Run service, proxied at
# dashboards.bidbrain.ai/d/central/, super-admin only) after ANY grid-core edit.
#
# ONE image serves everything (the-grid.html + server.js + src/ + config/ + scripts/), so
# unlike the client dashboards there is only this one script - no job/views split. The image
# is STATELESS: .dockerignore excludes data/ and .env; on Cloud Run the SQLite DB lives in
# /tmp (BRAIN_DATA_DIR) and re-seeds from config/central-import.json on every cold start.
# That means:
#   - what you deploy IS what is committed in config/ (central-clients.json map approvals,
#     central-import.json, reconcile-staged/, exec-kpis.json) - commit before deploying;
#   - NEVER do map approvals / inline edits on the LIVE instance - container writes are
#     ephemeral and vanish on the next cold start. Approve locally, commit, redeploy.
# `gcloud run services update --image` swaps ONLY the image - env vars and the service's
# standing flags (--no-cpu-throttling --min-instances=1, needed for the Executive tab's
# background refresh) are preserved.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\grid-core\deploy_grid.ps1
#   Needs a live gcloud login with access to bidbrain-analytics (ian@100.digital or
#   charles@100.digital). If tokens have gone stale you'll see "Reauthentication failed" -
#   run `gcloud auth login` first (interactive; the agent cannot do it for you).
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config ------------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                 # Artifact Registry docker repo (shared)
$SERVICE  = "central-grid"
$GRID_DIR = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $GRID_DIR 'server.js'))) { Die "no server.js in $GRID_DIR" }
if (-not (Test-Path (Join-Path $GRID_DIR 'Dockerfile'))) { Die "no Dockerfile in $GRID_DIR" }

# warn (don't block) on uncommitted grid-core changes - the image ships the working tree,
# but the repo convention is that live == a commit someone can check out.
$dirty = (& git -C $GRID_DIR status --porcelain -- . 2>$null)
if ($dirty) { Write-Host "!! grid-core has UNCOMMITTED changes - the image will include them:`n$dirty" -ForegroundColor Yellow }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
Write-Host "Rebuilding The Grid image ($SHA) ..."
gcloud builds submit $GRID_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build grid image"
Write-Host "Updating Cloud Run service $SERVICE (image swap only - env/flags preserved) ..."
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT; Must "update grid service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format "value(status.url)")
Write-Host ""
Write-Host "Done. $SERVICE is now on image $SHA." -ForegroundColor Green
Write-Host "  Raw URL (IAM-gated): $URL"
Write-Host "  Front door:          https://dashboards.bidbrain.ai/d/central/ (super-admin login)"
Write-Host "  Sanity check:        the sync route must 400 on a bogus client:"
Write-Host "                       POST $URL/api/central/sync?client=NotARealClient  -> 400 (via the proxy path)"
