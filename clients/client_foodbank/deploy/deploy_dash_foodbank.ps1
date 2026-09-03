# deploy_dash_foodbank.ps1 - redeploy ONLY the foodbank dashboard SERVICE after editing anything in
# dash/ (main.py, templates/, static/) or regenerating data/foodbank_sample.json. Rebuilds the image
# and swaps it onto the running Cloud Run service; leaves env vars, secrets and IAM untouched.
#
# *** PREPARED, NOT EXECUTED. Requires deploy_foodbank.ps1 to have stood the service up first. ***
# Mirrors clients/client_geyervalmont/dash/deploy_dash_geyervalmont.ps1.

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "foodbank-dash"
$CLIENT_DIR = Resolve-Path (Join-Path $PSScriptRoot "..")
$DASH_DIR = Join-Path $CLIENT_DIR "dash"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $DASH_DIR 'templates\dashboard.html'))) { Die "no templates\dashboard.html in $DASH_DIR" }

$SAMPLE_SRC = Join-Path $CLIENT_DIR "data\foodbank_sample.json"
$SAMPLE_DST = Join-Path $DASH_DIR "foodbank_sample.json"
if (-not (Test-Path $SAMPLE_SRC)) { Die "no data\foodbank_sample.json - run data\generate_sample.py first" }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
Write-Host "Rebuilding $SERVICE dash image ($SHA) ..."
Copy-Item $SAMPLE_SRC $SAMPLE_DST -Force
try {
  gcloud builds submit $DASH_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build dash image"
} finally { Remove-Item $SAMPLE_DST -Force -ErrorAction SilentlyContinue }
Write-Host "Updating Cloud Run service $SERVICE (image swap only - env/secrets preserved) ..."
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT; Must "update dash service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. $SERVICE redeployed (Cache-Control: no-store, so the change is live now):"
Write-Host "    $URL"
