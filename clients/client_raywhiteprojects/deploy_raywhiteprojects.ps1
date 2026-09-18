# deploy_raywhiteprojects.ps1 - one-shot, idempotent stand-up of the client_raywhiteprojects
# PREVIEW dashboard.
#
# PREVIEW ONLY. No Ray White Projects feed is connected (GA4 and GTM are not installed on
# monair.com.au yet, and the campaign goes live 25 Sep 2026), so this client has NO data pipeline:
# no BigQuery dataset, no sql/ views, no export job, no scheduler - and this script creates none
# of them. It stands up ONLY: APIs, Artifact Registry, the client bucket (left EMPTY), the web
# service account + IAM, the two secrets, and the DASH SERVICE. With the bucket empty, main.py's
# /data.json serves the baked-in ILLUSTRATIVE payload (dash/placeholder.json) behind the preview
# notice.
#
# This mirrors the Geyer Valmont / Lacevo / Burnet preview clients. Like those there is
# deliberately no -WithData switch, because there is nothing to switch on yet - see "FLIPPING
# PREVIEW TO LIVE" in README.md for the full ordered checklist.
#
# CLIENT KEY vs SLUG. The key is "raywhiteprojects" and the public slug is "raywhite-projects".
# They differ on purpose: every infrastructure name derives from the KEY, and a BigQuery dataset
# cannot contain a hyphen - "client_raywhite-projects" is not a legal dataset id. The estate
# already separates the two (cityperfume/city-perfume, tlm/the-little-marionette,
# sophiie/sophiie-ai). Do not "tidy" the key to match the slug.
#
#   HOW TO RUN (from the repo root OR from inside client_raywhiteprojects\):
#       .\clients\client_raywhiteprojects\deploy_raywhiteprojects.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Deploys need the ian@100.digital account (charles@ has no perms). Pin it for the session:
#       $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$BUCKET   = "bidbrain-analytics-raywhiteprojects-dash"
$SERVICE  = "raywhiteprojects-dash"
$WEB_SA   = "raywhiteprojects-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "raywhiteprojects-dash-password"
$SESSION_SECRET = "raywhiteprojects-dash-session-key"

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

# A brand-new service account is NOT immediately visible to the IAM policy APIs. On the FIRST run
# of this script the `service-accounts create` succeeds and the very next add-iam-policy-binding
# fails with
#   HTTPError 400: Service account raywhiteprojects-dash-web@... does not exist
# even though it was just created. That is propagation lag, not a real error - it bit the Sophiie
# standup and bites every new-client standup identically. So every SA-member binding goes through
# this retry instead of a bare Must. Existing-SA re-runs hit it first try and cost nothing.
function MustRetry($m, $sb, $tries = 6, $delay = 10) {
  for ($i = 1; $i -le $tries; $i++) {
    & $sb *> $null
    if ($LASTEXITCODE -eq 0) { return }
    if ($i -lt $tries) {
      Write-Host "   .. $m failed (attempt $i/$tries) - waiting ${delay}s for IAM to propagate" -ForegroundColor Yellow
      Start-Sleep -Seconds $delay
    }
  }
  Die "$m (still failing after $tries attempts)"
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

# Build context is the repo root. If we're inside client_raywhiteprojects\, step up.
if (-not (Test-Path 'clients/client_raywhiteprojects/dash/Dockerfile')) {
  if ((Test-Path 'dash/Dockerfile') -and ((Split-Path -Leaf (Get-Location)) -eq 'client_raywhiteprojects')) {
    Set-Location ../..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside client_raywhiteprojects\."; exit 1 }
}

Write-Host "Deploying client_raywhiteprojects PREVIEW to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
# No bigquery/cloudscheduler here on purpose - this preview has no pipeline to schedule.
Write-Host "[1/4] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry + bucket (NO BigQuery dataset - none needed yet) ---
Write-Host "[2/4] Artifact Registry + bucket ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
# Created EMPTY and stays empty until an export job exists. Its only role today is to let the
# service start with a real GCS_BUCKET value, so flipping to live later needs no env change - and
# it means the placeholder fallback path is exercised from day one rather than on go-live day.
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}

# ---- 3. Web service account + IAM + secrets ---------------------------------
Write-Host "[3/4] Service account, IAM + secrets ..."
if (-not (Exists { gcloud iam service-accounts describe $WEB_SA --project $PROJECT })) {
  gcloud iam service-accounts create ($WEB_SA.Split('@')[0]) --display-name "Ray White Projects dashboard web service" --project $PROJECT; Must "create web SA"
}
MustRetry "grant objectViewer to web SA" { gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" }

function New-SecretFromValue($name, $value) {
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $value, (New-Object System.Text.UTF8Encoding($false)))  # UTF-8, no BOM, no newline
    gcloud secrets create $name --data-file="$($tmp.FullName)" --project $PROJECT; Must "create secret $name"
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
}
if (-not (Exists { gcloud secrets describe $PW_SECRET --project $PROJECT })) {
  $pw = $env:DASH_PASSWORD
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
MustRetry "bind $PW_SECRET to web SA"      { gcloud secrets add-iam-policy-binding $PW_SECRET      --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT }
MustRetry "bind $SESSION_SECRET to web SA" { gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT }

# The PLATFORM also needs to read this dashboard's password. dashboards.bidbrain.ai proxies the
# dashboard at /d/raywhiteprojects/ and logs into the upstream ON THE USER'S BEHALF (main.py
# _upstream_pw -> _upstream_login), so without secretAccessor for platform-dash-web@ the tile's
# "Open preview ->" button 500s with PermissionDenied on secretmanager.versions.access - which is
# exactly what happened on the Geyer Valmont standup. secretVersionAdder + serviceAccountUser are
# the super-admin god-mode pair (reveal/rotate the password, open any dashboard).
$PLATFORM_SA = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
MustRetry "bind $PW_SECRET to the platform SA (proxy login)" { gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretAccessor"    --project $PROJECT }
MustRetry "bind $PW_SECRET rotate to the platform SA"        { gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretVersionAdder" --project $PROJECT }
MustRetry "grant the platform SA actAs on the web SA"        { gcloud iam service-accounts add-iam-policy-binding $WEB_SA --member="serviceAccount:${PLATFORM_SA}" --role="roles/iam.serviceAccountUser" --project $PROJECT }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 4. Dashboard service (serves placeholder.json - bucket is empty) -------
Write-Host "[4/4] Dashboard service ..."
$WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
gcloud builds submit clients/client_raywhiteprojects/dash --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=raywhiteprojects.json,CLIENT_KEY=raywhiteprojects" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
# Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
# own password auth, so remove the conflicting invoker gate. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null

# SSO_SECRET is what lets the platform's bb_sso cookie open this dashboard without a second
# password. It is granted + wired by scripts\enable_platform_sso.ps1 (which owns the shared
# `platform-sso-key` secret for the whole estate); until that runs, platform_sso.sso_allows returns
# False and this dashboard simply stays password-only. Deliberately NOT set here, so this script
# never has to know the shared key.
Write-Host "`nNOTE: run scripts\enable_platform_sso.ps1 -Keys raywhiteprojects to add it to the SSO allow-list"
Write-Host "      (without it the dashboard works, but only on its own password)."

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()

Write-Host "`n============================================================"
Write-Host "  DONE. Ray White Projects PREVIEW dashboard is live (password-gated):"
Write-Host "    $URL"
Write-Host "  Showing ILLUSTRATIVE data behind the preview notice (bucket is empty)."
Write-Host "  Portal tile: run bidbrain-platform\dash\set_raywhiteprojects_tile.py --yes"
Write-Host "  To go live later: see FLIPPING PREVIEW TO LIVE in clients\client_raywhiteprojects\README.md"
Write-Host "============================================================"
