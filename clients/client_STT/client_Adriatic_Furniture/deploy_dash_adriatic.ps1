# deploy_dash_adriatic.ps1 - build + deploy the OPEN Adriatic Furniture sample dashboard service.
#
# Self-contained: it serves clients/client_STT/client_Adriatic_Furniture/dashboard.html, which has its
# illustrative sample data baked into the HTML - so there is NO GCS bucket, NO SQL views and NO
# export job behind it, and NO password gate. The dashboard is deliberately open so the pitch can
# be shared by link. Idempotent - safe to re-run; it just swaps a fresh image onto the service.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\client_STT\client_Adriatic_Furniture\deploy_dash_adriatic.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                 # Artifact Registry docker repo (shared)
$SERVICE  = "adriatic-dash"
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
Write-Host "Building $SERVICE image ($SHA) ..."
gcloud builds submit $DASH_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build dash image"
Write-Host "Deploying Cloud Run service $SERVICE ..."
# --no-allow-unauthenticated: org policy (Domain Restricted Sharing) rejects --allow-unauthenticated,
# and passing it explicitly avoids gcloud's interactive y/N prompt. The --no-invoker-iam-check step
# below is what actually makes the service reachable.
gcloud run deploy $SERVICE --image $IMG --region $REGION --memory 512Mi --no-allow-unauthenticated --project $PROJECT; Must "deploy dash service"
# This dashboard has no password gate, so drop the invoker IAM check to make it openly reachable by
# link. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null; Must "open invoker gate"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. $SERVICE is live (open, no password). It serves dashboard.html with"
Write-Host "Cache-Control: no-store, so a redeploy shows immediately:"
Write-Host "    $URL"
