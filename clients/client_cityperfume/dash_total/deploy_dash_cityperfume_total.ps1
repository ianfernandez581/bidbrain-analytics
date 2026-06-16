# deploy_dash_cityperfume_total.ps1 - stand up / redeploy the 2nd City Perfume dashboard:
# the ALL-SALES variant (In-store POS + Website + Marketplace), service `cityperfume-total-dash`.
#
# This is a FRONT-END-ONLY fork of client_cityperfume/dash. It reuses EVERYTHING from the online-only
# dashboard's pipeline — the SAME private bucket + SAME cityperfume.json (the export job already ships
# every channel), the SAME web service account, and the SAME password + session secrets. So there is
# NO new dataset, view, export job, scheduler, bucket, SA or secret: only a 2nd Cloud Run service that
# serves this folder's all-sales dashboard.html. Idempotent — safe to re-run (it just swaps the image).
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\clients\client_cityperfume\dash_total\deploy_dash_cityperfume_total.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config (mirrors deploy_cityperfume.ps1; only SERVICE differs) ----------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                   # Artifact Registry docker repo (shared)
$SERVICE  = "cityperfume-total-dash"                     # the 2nd (all-sales) service
$BUCKET   = "bidbrain-analytics-cityperfume-dash"        # SAME private data bucket as the online dash
$WEB_SA   = "cityperfume-dash-web@${PROJECT}.iam.gserviceaccount.com"   # reuse the existing web SA
$PW_SECRET      = "cityperfume-dash-password"            # reuse the existing password
$SESSION_SECRET = "cityperfume-dash-session-key"         # reuse the existing session key
$DASH_DIR = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $DASH_DIR 'dashboard.html'))) { Die "no dashboard.html in $DASH_DIR" }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
Write-Host "Rebuilding $SERVICE dash image ($SHA) ..."
gcloud builds submit $DASH_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build dash image"

# Deploy (create-or-update). --no-allow-unauthenticated (+ --quiet): the org's Domain Restricted
# Sharing rejects public invokers, so the app's own password gate is the only door. The web SA already
# has objectViewer on the bucket + secretAccessor on both secrets (granted when the online dash stood
# up), so no IAM step is needed here.
Write-Host "Deploying Cloud Run service $SERVICE (reuses $WEB_SA, $BUCKET, cityperfume.json) ..."
gcloud run deploy $SERVICE --image $IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=cityperfume.json" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
# Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its own
# password auth, so remove the conflicting invoker gate. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`n============================================================"
Write-Host "  DONE. All-sales dashboard is live (password-gated, same password as the online one):"
Write-Host "    $URL"
Write-Host "============================================================"
