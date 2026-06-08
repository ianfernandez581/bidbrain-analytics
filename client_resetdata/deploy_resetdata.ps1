# deploy_resetdata.ps1 - one-shot, idempotent stand-up of the entire client_resetdata pipeline on GCP.
#
# Run it ONCE to provision everything; safe to re-run (anything that already exists is left alone),
# so if a step fails you can fix the cause and run it again.
#
#   HOW TO RUN (from the repo root OR from inside client_resetdata\):
#       .\client_resetdata\deploy_resetdata.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Uses gcloud + bq + git + the repo venv. The venv python applies the SQL views via
#   create_views.py (NOT `Get-Content | bq query`): one of ResetData's filters contains an EN-DASH
#   (Meta account 'Reset backup – Ad account'), and WinPS Get-Content re-encoding corrupts non-ASCII
#   in the SQL. create_views.py reads the files as UTF-8 so the en-dash survives.
#
#   DATA SOURCES: ResetData reads THREE shared raw datasets — raw_google_ads, raw_windsor, raw_ga4.
#   The job SA gets project-scoped roles/bigquery.dataViewer (below), which covers all three; do NOT
#   narrow it to a single dataset.

# ---- config (matches job/cloudbuild.yaml + dash/cloudbuild.yaml) ------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"                                 # Artifact Registry docker repo (shared)
$DATASET  = "client_resetdata"
$BUCKET   = "bidbrain-analytics-resetdata-dash"
$JOB      = "resetdata-export"
$SERVICE  = "resetdata-dash"
$JOB_SA   = "resetdata-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA   = "resetdata-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "resetdata-dash-password"
$SESSION_SECRET = "resetdata-dash-session-key"
$SCHEDULE_UTC   = "0 22 * * *"

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Get-Command bq     -ErrorAction SilentlyContinue)) { Write-Error "bq not found."; exit 1 }

# Build context for `gcloud builds submit .` is the repo root. If we're inside client_resetdata\, step up.
if (-not (Test-Path 'client_resetdata/job/cloudbuild.yaml')) {
  if ((Test-Path 'job/cloudbuild.yaml') -and ((Split-Path -Leaf (Get-Location)) -eq 'client_resetdata')) {
    Set-Location ..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside client_resetdata\."; exit 1 }
}

$PYTHON = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $PYTHON)) { Die "repo venv python not found at $PYTHON (needed to apply views)" }

Write-Host "Deploying client_resetdata to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/7] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry, bucket, dataset ----------------------------------
Write-Host "[2/7] Artifact Registry, bucket, dataset ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}
if (-not (Exists { bq --project_id=$PROJECT show --dataset "${PROJECT}:${DATASET}" })) {
  bq --location=$REGION --project_id=$PROJECT mk --dataset "${PROJECT}:${DATASET}"; Must "create dataset"
}

# ---- 3. Service accounts + IAM (least privilege) ----------------------------
Write-Host "[3/7] Service accounts + IAM ..."
function Ensure-Sa($email, $display) {
  $id = $email.Split('@')[0]
  if (-not (Exists { gcloud iam service-accounts describe $email --project $PROJECT })) {
    gcloud iam service-accounts create $id --display-name $display --project $PROJECT; Must "create SA $email"
  }
}
Ensure-Sa $JOB_SA "ResetData dashboard export job"
Ensure-Sa $WEB_SA "ResetData dashboard web service"

# JOB SA: run BigQuery jobs + read-only across BigQuery (the views read raw_google_ads + raw_windsor +
# raw_ga4 — the job writes nothing to BigQuery), and write the data bucket. Dataset-scoped grants need
# an org allowlist this project doesn't have, so use project-scoped read-only (dataViewer) — which also
# covers all THREE raw datasets at once. Do NOT narrow this to a single dataset.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser"   --condition=None | Out-Null; Must "grant jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataViewer" --condition=None | Out-Null; Must "grant dataViewer"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin"  | Out-Null; Must "grant objectAdmin to job SA"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" | Out-Null; Must "grant objectViewer to web SA"

# ---- 4. Secrets -------------------------------------------------------------
Write-Host "[4/7] Secrets ..."
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
gcloud secrets add-iam-policy-binding $PW_SECRET      --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $PW_SECRET to web SA"
gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SESSION_SECRET to web SA"

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 5. Views + export job --------------------------------------------------
Write-Host "[5/7] Applying views (create_views.py - UTF-8 safe for the en-dash filter) + building/deploying the export job ..."
& $PYTHON client_resetdata/create_views.py; Must "apply views via create_views.py"
$JOB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
gcloud builds submit client_resetdata/job --tag $JOB_IMG --region $REGION --project $PROJECT; Must "build export job image"
gcloud run jobs deploy $JOB --image $JOB_IMG --region $REGION --service-account $JOB_SA --memory 1Gi --project $PROJECT; Must "deploy export job"
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run export job (write resetdata.json)"

# ---- 6. Daily scheduler -----------------------------------------------------
Write-Host "[6/7] Daily scheduler ..."
$PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)'); $PNUM = "$PNUM".Trim()
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
$URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if (-not (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT })) {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)." } else { Write-Host "  Create the scheduler manually if needed." -ForegroundColor Yellow }
}

# ---- 7. Dashboard service (only if dashboard.html exists) -------------------
Write-Host "[7/7] Dashboard service ..."
if (Test-Path 'client_resetdata/dash/dashboard.html') {
  $WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
  gcloud builds submit client_resetdata/dash --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
  gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
    --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=resetdata.json" `
    --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
    --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
  # Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
  # own password auth, so remove the conflicting invoker gate. Idempotent.
  gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
  $URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
  Write-Host "`n============================================================"
  Write-Host "  DONE. Dashboard is live (password-gated):"
  Write-Host "    $URL"
  Write-Host "============================================================"
} else {
  Write-Host "  SKIPPED dash service - client_resetdata\dash\dashboard.html not found."
}
