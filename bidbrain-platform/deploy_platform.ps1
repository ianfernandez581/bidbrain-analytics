# deploy_platform.ps1 - one-shot, idempotent stand-up of the Bidbrain front-door platform
# (dashboards.bidbrain.ai). Web-only Cloud Run service whose agency/client registry is a single
# PRIVATE JSON in GCS (the same private-bucket pattern every dashboard uses - no database, no
# dataset, no export job, no scheduler).
#
#   HOW TO RUN (from the repo root OR from inside bidbrain-platform\):
#       .\bidbrain-platform\deploy_platform.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# What it provisions (all idempotent): APIs (run/build/AR/secretmanager/storage) -> private bucket
# bidbrain-analytics-platform-dash -> web SA + IAM (objectAdmin on that bucket + secretAccessor) ->
# 2 secrets (platform-dash-session-key = this app's own session signer; platform-sso-key = the
# SHARED cross-subdomain SSO signer, also injected into every dashboard by
# scripts\enable_platform_sso.ps1) -> build + deploy the service -> --no-invoker-iam-check ->
# seed the registry JSON from dash\config.py.
#
# After this: map dashboards.bidbrain.ai at the service in Cloudflare (CNAME + Host Header
# Override, same as every client dash), then run scripts\enable_platform_sso.ps1 so the
# dashboards trust the platform's SSO cookie. See bidbrain-platform\README.md.

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                  # Artifact Registry docker repo (shared)
$SERVICE  = "platform-dash"
$BUCKET   = "bidbrain-analytics-platform-dash"          # private; holds the registry JSON
$DATA_OBJECT = "platform.json"
$WEB_SA   = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
$SESSION_SECRET = "platform-dash-session-key"           # this app's own Flask session key
$SSO_SECRET     = "platform-sso-key"                    # SHARED SSO signer (platform + all dashboards)
$COOKIE_DOMAIN  = ".bidbrain.ai"

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

if (-not (Test-Path 'bidbrain-platform/dash/main.py')) {
  if ((Test-Path 'dash/main.py') -and ((Split-Path -Leaf (Get-Location)) -eq 'bidbrain-platform')) {
    Set-Location ..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside bidbrain-platform\."; exit 1 }
}

Write-Host "Deploying the Bidbrain platform front-door to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/6] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry + private registry bucket -------------------------
Write-Host "[2/6] Artifact Registry + bucket ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}

# ---- 3. Web service account + IAM (least privilege) -------------------------
Write-Host "[3/6] Service account + IAM ..."
$id = $WEB_SA.Split('@')[0]
if (-not (Exists { gcloud iam service-accounts describe $WEB_SA --project $PROJECT })) {
  gcloud iam service-accounts create $id --display-name "Bidbrain platform front-door web service" --project $PROJECT; Must "create web SA"
}
# objectAdmin (read+write) on its OWN bucket so the admin UI can persist edits to the registry JSON.
# No BigQuery, no other buckets, no datastore.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectAdmin" | Out-Null; Must "grant objectAdmin to web SA"

# ---- 4. Secrets -------------------------------------------------------------
Write-Host "[4/6] Secrets ..."
function New-RandomSecret($name) {
  if (Exists { gcloud secrets describe $name --project $PROJECT }) { return }
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, [Convert]::ToBase64String($bytes), (New-Object System.Text.UTF8Encoding($false)))
    gcloud secrets create $name --data-file="$($tmp.FullName)" --project $PROJECT; Must "create secret $name"
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
}
New-RandomSecret $SESSION_SECRET
New-RandomSecret $SSO_SECRET     # do NOT rotate casually: every dashboard verifies SSO cookies with this
gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SESSION_SECRET"
gcloud secrets add-iam-policy-binding $SSO_SECRET     --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SSO_SECRET"

# ---- 5. Build + deploy the service ------------------------------------------
Write-Host "[5/6] Build + deploy $SERVICE ..."
$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()
$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
gcloud builds submit bidbrain-platform/dash --tag $IMG --region $REGION --project $PROJECT; Must "build platform image"
gcloud run deploy $SERVICE --image $IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=${DATA_OBJECT},COOKIE_DOMAIN=${COOKIE_DOMAIN}" `
  --set-secrets "SESSION_SECRET=${SESSION_SECRET}:latest,SSO_SECRET=${SSO_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy platform service"
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null

# ---- 6. Seed the registry JSON from dash\config.py --------------------------
Write-Host "[6/6] Seeding the registry from config.py (idempotent; refuses to clobber existing data) ..."
$PYTHON = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (Test-Path $PYTHON) {
  & $PYTHON -m pip install -q google-cloud-storage 2>$null
  $env:GCS_BUCKET = $BUCKET; $env:DATA_OBJECT = $DATA_OBJECT
  & $PYTHON "bidbrain-platform\dash\seed_registry.py"
  if ($LASTEXITCODE -ne 0) { Write-Host "  Seed step did not complete - run it by hand (set `$env:GCS_BUCKET first): .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_registry.py" -ForegroundColor Yellow }
} else {
  Write-Host "  repo venv not found - seed manually: `$env:GCS_BUCKET='$BUCKET'; .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_registry.py" -ForegroundColor Yellow
}

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`n============================================================"
Write-Host "  DONE. Platform is live (password-gated):"
Write-Host "    $URL"
Write-Host "  NEXT: 1) point dashboards.bidbrain.ai at it in Cloudflare (CNAME + Host Header Override),"
Write-Host "        2) run scripts\enable_platform_sso.ps1 so dashboards trust the SSO cookie,"
Write-Host "        3) map each <c>.bidbrain.ai subdomain (so the .bidbrain.ai cookie reaches them)."
Write-Host "  Admin password default is 'bidbrain-admin-2026' - set a strong ADMIN_PW before seeding,"
Write-Host "  or rotate it later by editing the registry. See bidbrain-platform\README.md."
Write-Host "============================================================"
