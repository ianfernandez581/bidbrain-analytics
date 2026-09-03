# deploy_foodbank.ps1 - one-shot, idempotent stand-up of the client_foodbank PITCH dashboard.
#
# *** PREPARED, NOT EXECUTED. Do not run this until the pitch is won and Ian signs off. ***
#
# PREVIEW ONLY. This client has NO data pipeline: no BigQuery dataset, no sql/ views, no export job,
# no scheduler - and this script creates none of them. It stands up ONLY: APIs, Artifact Registry,
# the client bucket (left EMPTY), the web service account + IAM, the two secrets, and the DASH
# SERVICE, which serves the baked-in SAMPLE payload (data/foodbank_sample.json) while
# dash/main.py's DATA_MODE is "sample". Mirrors clients/client_geyervalmont/deploy_geyervalmont.ps1.
#
#   HOW TO RUN (from the repo root OR from inside client_foodbank\):
#       .\clients\client_foodbank\deploy\deploy_foodbank.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Deploys need the ian@100.digital account (charles@ has no perms). This repo's VS Code window is
#   pinned to the `personal` gcloud config via CLOUDSDK_ACTIVE_CONFIG_NAME - never `gcloud config set`.

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$CLIENT   = "foodbank"
$BUCKET   = "bidbrain-analytics-${CLIENT}-dash"
$SERVICE  = "${CLIENT}-dash"
$WEB_SA   = "${CLIENT}-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "${CLIENT}-dash-password"
$SESSION_SECRET = "${CLIENT}-dash-session-key"

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }
# A brand-new service account is not immediately visible to the IAM policy APIs (propagation lag).
# Retry each SA-member binding so the FIRST run cannot fail this way (the sophiie standup lesson).
function MustRetry($sb, $m) {
  for ($i = 1; $i -le 6; $i++) { & $sb *> $null; if ($LASTEXITCODE -eq 0) { return }; Start-Sleep -Seconds 10 }
  Die $m
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

# Build context is the repo root. If we're inside client_foodbank\ (or deploy\), step up.
$here = Get-Location
if (-not (Test-Path 'clients/client_foodbank/dash/Dockerfile')) {
  if (Test-Path (Join-Path $PSScriptRoot '..\..\..\clients\client_foodbank\dash\Dockerfile')) {
    Set-Location (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')); Write-Host "Moved to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside client_foodbank\."; exit 1 }
}

Write-Host "Deploying client_foodbank PREVIEW to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/4] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry + bucket (NO BigQuery dataset - none needed yet) ---
Write-Host "[2/4] Artifact Registry + bucket ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}

# ---- 3. Web service account + IAM + secrets ---------------------------------
Write-Host "[3/4] Service account, IAM + secrets ..."
if (-not (Exists { gcloud iam service-accounts describe $WEB_SA --project $PROJECT })) {
  gcloud iam service-accounts create ($WEB_SA.Split('@')[0]) --display-name "Foodbank Australia dashboard web service" --project $PROJECT; Must "create web SA"
}
MustRetry { gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" } "grant objectViewer to web SA"

function New-SecretFromValue($name, $value) {
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $value, (New-Object System.Text.UTF8Encoding($false)))  # UTF-8, no BOM, no newline
    gcloud secrets create $name --data-file="$($tmp.FullName)" --project $PROJECT; Must "create secret $name"
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
}
if (-not (Exists { gcloud secrets describe $PW_SECRET --project $PROJECT })) {
  $pw = $env:FOODBANK_DASH_PASSWORD
  if ([string]::IsNullOrEmpty($pw)) {
    $secure = Read-Host "  Choose the dashboard password (viewers type this to log in)" -AsSecureString
    $pw = [System.Net.NetworkCredential]::new('', $secure).Password
  }
  New-SecretFromValue $PW_SECRET $pw
}
if (-not (Exists { gcloud secrets describe $SESSION_SECRET --project $PROJECT })) {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  New-SecretFromValue $SESSION_SECRET ([Convert]::ToBase64String($bytes))
}
MustRetry { gcloud secrets add-iam-policy-binding $PW_SECRET      --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT } "bind $PW_SECRET to web SA"
MustRetry { gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT } "bind $SESSION_SECRET to web SA"

# The PLATFORM proxies every dashboard at /d/<client>/ and logs into the upstream on the user's
# behalf, so it needs to read this password too (the geyervalmont standup lesson: without it the
# portal tile 500s). secretVersionAdder + serviceAccountUser are the super-admin reveal/rotate pair.
$PLATFORM_SA = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
MustRetry { gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretAccessor"    --project $PROJECT } "bind $PW_SECRET to the platform SA (proxy login)"
MustRetry { gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretVersionAdder" --project $PROJECT } "bind $PW_SECRET rotate to the platform SA"
MustRetry { gcloud iam service-accounts add-iam-policy-binding $WEB_SA --member="serviceAccount:${PLATFORM_SA}" --role="roles/iam.serviceAccountUser" --project $PROJECT } "grant the platform SA actAs on the web SA"

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 4. Dashboard service ---------------------------------------------------
Write-Host "[4/4] Dashboard service ..."
# The build context is dash/ only, so the sample payload is copied in for the build and removed after.
$DASH_DIR = "clients/client_foodbank/dash"
$SAMPLE_SRC = "clients/client_foodbank/data/foodbank_sample.json"
$SAMPLE_DST = Join-Path $DASH_DIR "foodbank_sample.json"
if (-not (Test-Path $SAMPLE_SRC)) { Die "no $SAMPLE_SRC - run data\generate_sample.py first" }
Copy-Item $SAMPLE_SRC $SAMPLE_DST -Force
try {
  $WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
  gcloud builds submit $DASH_DIR --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
} finally { Remove-Item $SAMPLE_DST -Force -ErrorAction SilentlyContinue }
gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=${CLIENT}.json,CLIENT_KEY=${CLIENT}" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
# Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
# own password auth, so remove the conflicting invoker gate. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()

Set-Location $here
Write-Host "`n============================================================"
Write-Host "  DONE. Foodbank Australia PREVIEW dashboard is live (password-gated):"
Write-Host "    $URL"
Write-Host "  Serving the SAMPLE payload (DATA_MODE=sample). To go live: see README.md -> Flipping to live."
Write-Host "============================================================"
