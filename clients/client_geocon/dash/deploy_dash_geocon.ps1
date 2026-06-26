# deploy_dash_geocon.ps1 - redeploy ONLY the geocon dashboard SERVICE after editing
# dash/dashboard.html or dash/main.py. Rebuilds the dash image and swaps it onto the running Cloud
# Run service; leaves env vars, secrets, the export JOB, SQL views, and all IAM untouched.

# ---- config (matches dash/cloudbuild.yaml) ----------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "geocon-dash"
$DASH_DIR = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $DASH_DIR 'dashboard.html'))) { Die "no dashboard.html in $DASH_DIR" }

# ---- copy the logo from creatives/ into the dash build context --------------
$LOGO_SRC = Join-Path $DASH_DIR "..\creatives\Gateway-Braddon-Logo.png"
$LOGO_DST = Join-Path $DASH_DIR "logo.png"
if (Test-Path $LOGO_SRC) {
    Copy-Item -Path $LOGO_SRC -Destination $LOGO_DST -Force
    Write-Host "Copied logo.png into dash build context."
} else {
    Write-Host "WARNING: logo not found at $LOGO_SRC - building without it." -ForegroundColor Yellow
}

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
Write-Host "Rebuilding $SERVICE dash image ($SHA) ..."
gcloud builds submit $DASH_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build dash image"
Write-Host "Updating Cloud Run service $SERVICE (image swap only - env/secrets preserved) ..."
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT; Must "update dash service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. $SERVICE redeployed. It serves dashboard.html with Cache-Control: no-store, so the change is live now:"
Write-Host "    $URL"
