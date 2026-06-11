# deploy_dash_status.ps1 - redeploy ONLY the status (meta) dashboard SERVICE after editing
# dash/dashboard.html or dash/main.py. Rebuilds the dash image and swaps it onto the running Cloud
# Run service; leaves env vars, secrets, the export JOB, and all IAM untouched. The common, fast path.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\status_dashboard\dash\deploy_dash_status.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "status-dash"
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
Write-Host "Updating Cloud Run service $SERVICE (image swap only - env/secrets preserved) ..."
gcloud run services update $SERVICE --image $IMG --region $REGION --project $PROJECT; Must "update dash service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. $SERVICE redeployed (serves dashboard.html with Cache-Control: no-store, so it's live now):"
Write-Host "    $URL"
