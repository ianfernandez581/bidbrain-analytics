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
# Greenlight ONLY runs on the Kimi Code subscription key (kimi-api-key secret,
# Charles's kimi.com plan) via the GREENLIGHT_* env pair - extract.js prefers
# GREENLIGHT_API_KEY/GREENLIGHT_BASE_URL over ANTHROPIC_*, so Brain/plan-reader
# stay on the Anthropic key above. To revert Greenlight to Anthropic:
#   gcloud run services update central-grid --region australia-southeast1 `
#     --remove-env-vars GREENLIGHT_BASE_URL,EXPECTED_MODEL --remove-secrets GREENLIGHT_API_KEY
gcloud secrets add-iam-policy-binding kimi-api-key --member="serviceAccount:$RUNTIME_SA" `
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

# Connections tab reads windsor_connections.json (written hourly by the windsor-connections-probe
# job, ingest/windsor_data_pull/connections/) from the STATUS bucket, and "Probe now" runs that
# job through the Cloud Run Admin API. Read-only on the bucket; run.invoker on the job. Idempotent.
$CONN_BUCKET = "bidbrain-analytics-status-dash"
$CONN_JOB    = "windsor-connections-probe"
gcloud storage buckets add-iam-policy-binding "gs://$CONN_BUCKET" --member="serviceAccount:$RUNTIME_SA" `
    --role="roles/storage.objectViewer" --project $PROJECT *> $null
gcloud run jobs add-iam-policy-binding $CONN_JOB --region $REGION --project $PROJECT `
    --member="serviceAccount:$RUNTIME_SA" --role="roles/run.invoker" *> $null   # no-op until the job exists

Write-Host "Updating Cloud Run service $SERVICE (image swap + state bucket + secrets; other env/flags preserved) ..."
# --update-env-vars / --update-secrets MERGE (they never clear the others), so
# re-asserting these every deploy is idempotent and self-heals a service that
# lost them. GREENLIGHT_ENABLED is deliberately NOT set here: the tab ships
# dark by default; flip it manually when Ian signs off:
#   gcloud run services update central-grid --region australia-southeast1 `
#     --update-env-vars GREENLIGHT_ENABLED=true --timeout 600
# (--timeout 600 because the extraction call runs ~320s synchronously in the
# request; Cloud Run's default 300s would cut it off. TODO: background job.)
# --remove-env-vars SCRUBS the sandbox-only vars set by deploy_grid_preview.ps1. Cloud Run has
# no per-revision env: a preview deploy leaves CENTRAL_IMPORT_PATH / CENTRAL_EXTRA_PATH /
# GRID_STATE_OBJECT on the SERVICE TEMPLATE, and this command builds its revision FROM that
# template - so without the scrub the next live deploy would boot the 14-row sandbox seed and
# read the preview state blob, in front of every super-admin. Removing a var that is not set is
# a no-op, so this is safe and idempotent on a service that has never had a preview.
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT `
    --update-env-vars "GRID_STATE_BUCKET=$STATE_BUCKET,GREENLIGHT_BUCKET=$DUMPS_BUCKET,GREENLIGHT_BASE_URL=https://api.kimi.com/coding,EXPECTED_MODEL=kimi-for-coding,GRID_CONNECTIONS_BUCKET=$CONN_BUCKET,GRID_CONNECTIONS_JOB=$CONN_JOB" `
    --remove-env-vars "CENTRAL_IMPORT_PATH,CENTRAL_EXTRA_PATH,GRID_STATE_OBJECT" `
    --update-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,GREENLIGHT_API_KEY=kimi-api-key:latest"; Must "update grid service"

# TRAFFIC GUARD. A preview deploy (deploy_grid_preview.ps1) uses --no-traffic, which PINS the
# service to whichever revision was serving at the time. Cloud Run then stops auto-promoting: this
# script keeps building and deploying revisions that receive 0% while printing success, and live
# silently stays on an old image. It cost us exactly that on 2026-09-03 - the ship said
# "[OK] deployed central-grid" and live ran a three-week-old build.
# So: verify the revision we just created is actually serving, and if not, say so LOUDLY and print
# the exact fix. NOTE it names THAT revision rather than --to-latest: when a preview revision is the
# newest, --to-latest would promote the PREVIEW to live, which is the opposite of what you want.
$svcJson = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format json | ConvertFrom-Json)
$newRev  = "$($svcJson.status.latestCreatedRevisionName)".Trim()
$serving = @($svcJson.status.traffic | Where-Object { $_.percent -gt 0 } | ForEach-Object { $_.revisionName })
if ($newRev -and ($serving -notcontains $newRev)) {
    Write-Host ""
    Write-Host "!! DEPLOYED BUT NOT SERVING. Revision $newRev has 0% of traffic - LIVE IS UNCHANGED." -ForegroundColor Red
    Write-Host "   The service's traffic is PINNED (a --no-traffic preview deploy does this)." -ForegroundColor Yellow
    Write-Host "   Currently serving: $($serving -join ', ')" -ForegroundColor Yellow
    Write-Host "   Send live to what you just built:" -ForegroundColor Yellow
    Write-Host "     gcloud run services update-traffic $SERVICE --region $REGION --to-revisions ${newRev}=100" -ForegroundColor Yellow
    Write-Host "   (do NOT use --to-latest while a preview revision exists - it would promote the PREVIEW)" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host "[OK] $newRev is serving traffic." -ForegroundColor Green
}

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format "value(status.url)")
Write-Host ""
Write-Host "Done. $SERVICE is now on image $SHA." -ForegroundColor Green
Write-Host "  Raw URL (IAM-gated): $URL"
Write-Host "  Front door:          https://dashboards.bidbrain.ai/d/central/ (super-admin login)"
Write-Host "  Sanity check:        the sync route must 400 on a bogus client:"
Write-Host "                       POST $URL/api/central/sync?client=NotARealClient  -> 400 (via the proxy path)"
