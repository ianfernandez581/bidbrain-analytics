# deploy_dash_raywhiteprojects.ps1 - redeploy ONLY the Ray White Projects dashboard SERVICE after
# editing dash/dashboard.html, dash/main.py, dash/placeholder.json or dash/internal_notes.json.
# Rebuilds the dash image and swaps it onto the running Cloud Run service; leaves env vars,
# secrets and all IAM untouched.
#
# This is also what /ship and /go run for any change under clients/client_raywhiteprojects/dash/.

# ---- config (matches dash/cloudbuild.yaml) ----------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "raywhiteprojects-dash"
$DASH_DIR = $PSScriptRoot

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Test-Path (Join-Path $DASH_DIR 'dashboard.html'))) { Die "no dashboard.html in $DASH_DIR" }
# The preview renders from this; without it /data.json 404s and the page shows its error state.
if (-not (Test-Path (Join-Path $DASH_DIR 'placeholder.json'))) { Die "no placeholder.json in $DASH_DIR (re-run gen_placeholder.py)" }
if (-not (Test-Path (Join-Path $DASH_DIR 'internal_notes.json'))) { Die "no internal_notes.json in $DASH_DIR (staff tab needs it)" }
# NOTE: no logo.svg / icon.png check, unlike the other tenants. No Ray White Projects artwork has
# been supplied, so the lockup is a typographic stand-in in markup and the favicon is an inline
# data URI - there is deliberately no binary brand asset in this unit yet. When artwork lands,
# gen_brand_assets.py adds those files, the Dockerfile COPY line and the guards here together.

# Cheap guard against shipping a dashboard whose JS does not parse - the page would render its
# error state for every viewer and nothing server-side would fail.
$venv = Join-Path $DASH_DIR '..\..\..\.venv\Scripts\python.exe'
if (Test-Path $venv) {
  & $venv (Join-Path $DASH_DIR '..\..\..\scripts\_validate_dash_js.py') (Join-Path $DASH_DIR 'dashboard.html')
  Must "dashboard.html JS did not parse"
}

# The payload is GENERATED and its generator asserts that every KPI reconciles with the table
# under it. Re-run it here so a hand-edited placeholder.json can never be what ships.
$gen = Join-Path $DASH_DIR '..\gen_placeholder.py'
if ((Test-Path $venv) -and (Test-Path $gen)) {
  & $venv $gen
  Must "gen_placeholder.py failed its reconciliation assertions"
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
