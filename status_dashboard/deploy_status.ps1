# deploy_status.ps1 - one-shot, idempotent stand-up of the META / pipeline-status dashboard on GCP.
#
# This is the "meta dashboard" (status.bidbrain.ai): one gated screen that shows, for every
# Snowflake-sourced client, whether a stale dashboard is Transmission's fault (Snowflake source
# not updating) or 100% Digital's (our pipeline behind) -- and proves each dashboard number equals
# the number in Snowflake.
#
# Run it ONCE to provision everything; safe to re-run (anything that already exists is left alone),
# so if a step fails you can fix the cause and run it again.
#
#   HOW TO RUN (from the repo root OR from inside status_dashboard\):
#       .\status_dashboard\deploy_status.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Uses gcloud + git only. Unlike a client stand-up there is NO BigQuery dataset and NO SQL views:
#   the status job reads OTHER clients' buckets + Snowflake/BigQuery metadata and writes one JSON.

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                   # Artifact Registry docker repo (shared)
$BUCKET   = "bidbrain-analytics-status-dash"             # the status dashboard's own private bucket
$JOB      = "status-export"
$SERVICE  = "status-dash"
$JOB_SA   = "status-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA   = "status-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "status-dash-password"
$SESSION_SECRET = "status-dash-session-key"
$SF_SECRET      = "snowflake-bq-key"                     # EXISTING shared Snowflake key (reused, never created here)
$SCHEDULE_UTC   = "*/15 * * * *"                         # idle ticks are metadata-only; counts self-gate on freshness

# Every Snowflake-sourced client whose bucket the job must read (<client>.json). Keep in sync with
# the CLIENTS dict in status_dashboard/job/main.py.
$CLIENT_BUCKETS = @(
  "bidbrain-analytics-mongodb-dash",
  "bidbrain-analytics-cloudflare-dash",
  "bidbrain-analytics-stt-dash",
  "bidbrain-analytics-hireright-dash",
  "bidbrain-analytics-schneider-dash",
  "bidbrain-analytics-proptrack-dash"
)

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

# Build context for `gcloud builds submit` is the stage folder. If we're inside status_dashboard\, step up.
if (-not (Test-Path 'status_dashboard/job/Dockerfile')) {
  if ((Test-Path 'job/Dockerfile') -and ((Split-Path -Leaf (Get-Location)) -eq 'status_dashboard')) {
    Set-Location ..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside status_dashboard\."; exit 1 }
}

Write-Host "Deploying the meta/status dashboard to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/6] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry + the status bucket -------------------------------
Write-Host "[2/6] Artifact Registry + status bucket ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create status bucket"
}

# ---- 3. Service accounts + IAM (least privilege) ----------------------------
Write-Host "[3/6] Service accounts + IAM ..."
function Ensure-Sa($email, $display) {
  $id = $email.Split('@')[0]
  if (-not (Exists { gcloud iam service-accounts describe $email --project $PROJECT })) {
    gcloud iam service-accounts create $id --display-name $display --project $PROJECT; Must "create SA $email"
  }
}
Ensure-Sa $JOB_SA "Status dashboard export job"
Ensure-Sa $WEB_SA "Status dashboard web service"

# JOB SA: read BigQuery metadata (raw_snowflake __TABLES__ last_modified) + run query jobs; write its
# own status bucket; READ every client bucket's <client>.json; read the shared Snowflake key secret.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser"   --condition=None | Out-Null; Must "grant jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataViewer" --condition=None | Out-Null; Must "grant dataViewer"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin"  | Out-Null; Must "grant objectAdmin (status bucket) to job SA"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" | Out-Null; Must "grant objectViewer (status bucket) to web SA"
foreach ($cb in $CLIENT_BUCKETS) {
  gcloud storage buckets add-iam-policy-binding "gs://${cb}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectViewer" | Out-Null; Must "grant objectViewer on $cb to job SA"
}
# The status job reads the EXISTING shared Snowflake key (created during the first Snowflake client
# stand-up). It is never created here -- only granted to the status job SA.
gcloud secrets add-iam-policy-binding $SF_SECRET --member="serviceAccount:${JOB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SF_SECRET to job SA"

# ---- 4. Secrets (dashboard password + session key) --------------------------
Write-Host "[4/6] Secrets ..."
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
    $secure = Read-Host "  Choose the status dashboard password (viewers type this to log in)" -AsSecureString
    $pw = [System.Net.NetworkCredential]::new('', $secure).Password
  }
  New-SecretFromValue $PW_SECRET $pw
}
if (-not (Exists { gcloud secrets describe $SESSION_SECRET --project $PROJECT })) {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  New-SecretFromValue $SESSION_SECRET ([Convert]::ToBase64String($bytes))
}
gcloud secrets add-iam-policy-binding $PW_SECRET      --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $PW_SECRET to web SA"
gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SESSION_SECRET to web SA"

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 5. Export job (build + deploy + run once) ------------------------------
Write-Host "[5/6] Building + deploying the status-export job ..."
$JOB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
gcloud builds submit status_dashboard/job --tag $JOB_IMG --region $REGION --project $PROJECT; Must "build export job image"
gcloud run jobs deploy $JOB --image $JOB_IMG --region $REGION --service-account $JOB_SA --memory 1Gi `
  --set-secrets "SNOWFLAKE_KEY=${SF_SECRET}:latest" --project $PROJECT; Must "deploy export job"
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run export job (write status.json)"

# Daily/periodic scheduler (idempotent). The job self-gates the expensive Snowflake counts on
# freshness, so most ticks are metadata-only.
$PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)'); $PNUM = "$PNUM".Trim()
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
$URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if (-not (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT })) {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)." } else { Write-Host "  Create the scheduler manually if needed." -ForegroundColor Yellow }
}

# ---- 6. Dashboard service (only if dashboard.html exists) -------------------
Write-Host "[6/6] Dashboard service ..."
if (Test-Path 'status_dashboard/dash/dashboard.html') {
  $WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
  gcloud builds submit status_dashboard/dash --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
  # --no-allow-unauthenticated avoids gcloud's interactive y/N prompt (the org enforces Domain
  # Restricted Sharing, so public invoke is rejected anyway). The app does its OWN password auth, so
  # the conflicting invoker gate is then removed with --no-invoker-iam-check just below.
  gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
    --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=status.json" `
    --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
    --memory 512Mi --no-allow-unauthenticated --project $PROJECT; Must "deploy dash service"
  # Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
  # own password auth, so remove the conflicting invoker gate. Idempotent.
  gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
  $URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
  Write-Host "`n============================================================"
  Write-Host "  DONE. Meta/status dashboard is live (password-gated):"
  Write-Host "    $URL"
  Write-Host "  Point status.bidbrain.ai at it in Cloudflare DNS (same as the client dashboards)."
  Write-Host "============================================================"
} else {
  Write-Host "  SKIPPED dash service - status_dashboard\dash\dashboard.html not found."
}
