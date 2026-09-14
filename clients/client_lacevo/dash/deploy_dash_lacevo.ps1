# deploy_dash_lacevo.ps1 - redeploy ONLY the lacevo dashboard SERVICE after editing
# dash/dashboard.html, dash/main.py, dash/placeholder.json or dash/internal_notes.json. Rebuilds the
# dash image and swaps it onto the running Cloud Run service; leaves env vars, secrets and all IAM
# untouched.
#
# This is also what /ship and /go run for any change under clients/client_lacevo/dash/.

# ---- config (matches dash/cloudbuild.yaml) ----------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "lacevo-dash"
$DASH_DIR = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $DASH_DIR 'dashboard.html'))) { Die "no dashboard.html in $DASH_DIR" }
# The Lacevo brand ships in THREE colourways, all derived from creatives/LACEVO-master.webp by
# gen_brand_assets.py, because the surfaces differ:
#   - a bone HORIZONTAL lockup inlined as base64 inside dashboard.html (inlined because a
#     root-relative path does not resolve behind the platform proxy at /d/lacevo/)
#   - dash/logo.png, the bone STACKED lockup, served at /logo.png for the dark login card
#   - dash/icon.png, the CLAY droplet, served at /icon.png for the browser tab
# Regenerate them, never hand-edit. See README.md -> "The logo".
if (-not (Test-Path (Join-Path $DASH_DIR 'logo.png'))) { Die "no logo.png in $DASH_DIR (the login card needs the bone lockup)" }
if (-not (Test-Path (Join-Path $DASH_DIR 'icon.png'))) { Die "no icon.png in $DASH_DIR (browser tab icon; re-run gen_brand_assets.py)" }
# The preview renders from this; without it /data.json 404s and the page shows its error state.
if (-not (Test-Path (Join-Path $DASH_DIR 'placeholder.json'))) { Die "no placeholder.json in $DASH_DIR (re-run gen_placeholder.py)" }
if (-not (Test-Path (Join-Path $DASH_DIR 'internal_notes.json'))) { Die "no internal_notes.json in $DASH_DIR (staff tab needs it)" }

# Cheap guard against shipping a dashboard whose JS does not parse - the page would render its
# error state for every viewer and nothing server-side would fail.
$venv = Join-Path $DASH_DIR '..\..\..\.venv\Scripts\python.exe'
if (Test-Path $venv) {
  & $venv (Join-Path $DASH_DIR '..\..\..\scripts\_validate_dash_js.py') (Join-Path $DASH_DIR 'dashboard.html')
  Must "dashboard.html JS did not parse"
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
