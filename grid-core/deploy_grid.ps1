# deploy_grid.ps1 - redeploy The Grid (the `central-grid` Cloud Run service, proxied at
# dashboards.bidbrain.ai/d/central/, super-admin only) after ANY grid-core edit.
#
# ONE image serves everything (the-grid.html + server.js + src/ + config/ + scripts/), so
# unlike the client dashboards there is only this one script - no job/views split.
#
# STATE (changed 2026-08-04): the image is still stateless, but the DB no longer is. The
# SQLite file lives in /tmp (BRAIN_DATA_DIR) as before, and is now loaded from and saved
# back to gs://<GRID_STATE_BUCKET>/grid-state/brain-historical.db (src/brain/persist.js).
# Before this, /tmp died with the instance, so every cold start re-seeded from
# config/central-import.json and a sync had nowhere to land - which is why the platform
# tile read "never synced" forever. That is fixed; the notes below still apply:
#   - what you deploy IS what is committed in config/ (central-clients.json map approvals,
#     central-import.json, reconcile-staged/, exec-kpis.json) - commit before deploying;
#   - map approvals STILL belong locally + committed: /approve writes central-clients.json,
#     which is baked into the image, NOT into the persisted DB. Inline campaign edits and
#     sync results DO now survive, because they live in the DB.
#   - the state file is versioned in GCS, so a bad write can be rolled back.
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
$STATE_BUCKET = "bidbrain-analytics-grid-state"        # durable SQLite state (see src/brain/persist.js)
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
# Greenlight (plan-side checker tab) needs the Anthropic key at runtime. The
# funded key is version 2+ of the anthropic-api-key secret (v1 is the old
# unfunded org key - if extraction 400s on billing, check which version is
# latest and whether the account still has credits). Grant is idempotent.
$RUNTIME_SA = "516554645957-compute@developer.gserviceaccount.com"
gcloud secrets add-iam-policy-binding anthropic-api-key --member="serviceAccount:$RUNTIME_SA" `
    --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null

# Greenlight analyses (per-campaign file dumps + run history) mirror to GCS so
# the library survives Cloud Run cold starts (/tmp does not). Idempotent.
$DUMPS_BUCKET = "bidbrain-campaign-dumps"
gcloud storage buckets describe "gs://$DUMPS_BUCKET" --project $PROJECT *> $null
if ($LASTEXITCODE -ne 0) {
  gcloud storage buckets create "gs://$DUMPS_BUCKET" --location $REGION --project $PROJECT --uniform-bucket-level-access; Must "create dumps bucket"
}
gcloud storage buckets add-iam-policy-binding "gs://$DUMPS_BUCKET" --member="serviceAccount:$RUNTIME_SA" `
    --role="roles/storage.objectAdmin" --project $PROJECT *> $null

Write-Host "Updating Cloud Run service $SERVICE (image swap + state bucket + secrets; other env/flags preserved) ..."
# --update-env-vars / --update-secrets MERGE (they never clear the others), so
# re-asserting these every deploy is idempotent and self-heals a service that
# lost them. GREENLIGHT_ENABLED is deliberately NOT set here: the tab ships
# dark by default; flip it manually when Ian signs off:
#   gcloud run services update central-grid --region australia-southeast1 `
#     --update-env-vars GREENLIGHT_ENABLED=true --timeout 600
# (--timeout 600 because the extraction call runs ~320s synchronously in the
# request; Cloud Run's default 300s would cut it off. TODO: background job.)
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT `
    --update-env-vars "GRID_STATE_BUCKET=$STATE_BUCKET,GREENLIGHT_BUCKET=$DUMPS_BUCKET" `
    --update-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest"; Must "update grid service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format "value(status.url)")
Write-Host ""
Write-Host "Done. $SERVICE is now on image $SHA." -ForegroundColor Green
Write-Host "  Raw URL (IAM-gated): $URL"
Write-Host "  Front door:          https://dashboards.bidbrain.ai/d/central/ (super-admin login)"
Write-Host "  Sanity check:        the sync route must 400 on a bogus client:"
Write-Host "                       POST $URL/api/central/sync?client=NotARealClient  -> 400 (via the proxy path)"
