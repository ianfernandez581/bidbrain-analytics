# deploy_vmch.ps1 - one-shot, idempotent stand-up of the entire client_vmch pipeline on GCP.
#
# Run it ONCE to provision everything; safe to re-run.
#
#   HOW TO RUN (from the repo root):
#       .\clients\client_vmch\deploy_vmch.ps1
#
#   Uses gcloud + bq + git only.

# ---- config ----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$DATASET  = "client_vmch"
$BUCKET   = "bidbrain-analytics-vmch-dash"
$JOB      = "vmch-export"
$SERVICE  = "vmch-dash"
$JOB_SA   = "vmch-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA   = "vmch-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "vmch-dash-password"
$SESSION_SECRET = "vmch-dash-session-key"
$SCHEDULE_UTC   = "*/10 * * * *"

function Die($m)  { Write-Host "!! Failed: $m. Fix and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Get-Command bq     -ErrorAction SilentlyContinue)) { Write-Error "bq not found."; exit 1 }

Write-Host "Deploying client_vmch to $PROJECT ($REGION)`n"

# ---- 1. APIs ---------------------------------------------------------------
Write-Host "[1/7] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry, bucket, dataset ---------------------------------
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

# ---- 3. Service accounts + IAM --------------------------------------------
Write-Host "[3/7] Service accounts + IAM ..."
function Ensure-Sa($email, $display) {
  $id = $email.Split('@')[0]
  if (-not (Exists { gcloud iam service-accounts describe $email --project $PROJECT })) {
    gcloud iam service-accounts create $id --display-name $display --project $PROJECT; Must "create SA $email"
  }
}
Ensure-Sa $JOB_SA "VMCH dashboard export job"
Ensure-Sa $WEB_SA "VMCH dashboard web service"

gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser"   --condition=None | Out-Null; Must "grant jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataViewer" --condition=None | Out-Null; Must "grant dataViewer"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin"  | Out-Null; Must "grant objectAdmin to job SA"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" | Out-Null; Must "grant objectViewer to web SA"

# ---- 4. Secrets ------------------------------------------------------------
Write-Host "[4/7] Secrets ..."
function New-SecretFromValue($name, $value) {
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $value, (New-Object System.Text.UTF8Encoding($false)))
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

# ---- 5. Views + export job -------------------------------------------------
Write-Host "[5/7] Applying views + building/deploying the export job ..."
$sqlDir = "clients/client_vmch/sql"
$sqlFiles = Get-ChildItem $sqlDir -Filter '*.sql' | Sort-Object Name
foreach ($sf in $sqlFiles) {
  Write-Host "     applying $($sf.Name)"
  Get-Content $sf.FullName -Raw | bq query --project_id=$PROJECT --location=$REGION --use_legacy_sql=false *> $null
  Must "apply view $($sf.Name)"
}
$JOB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
gcloud builds submit "clients/client_vmch/job" --tag $JOB_IMG --region $REGION --project $PROJECT; Must "build export job image"
gcloud run jobs deploy $JOB --image $JOB_IMG --region $REGION --service-account $JOB_SA --memory 1Gi --project $PROJECT; Must "deploy export job"
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait; Must "run export job (write vmch.json)"

# ---- 6. Daily scheduler ----------------------------------------------------
Write-Host "[6/7] Daily scheduler ..."
$PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)').Trim()
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
$URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if (-not (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT })) {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)." } else { Write-Host "  Create the scheduler manually if needed." -ForegroundColor Yellow }
}

# ---- 7. Dashboard service --------------------------------------------------
Write-Host "[7/7] Dashboard service ..."
if (Test-Path 'clients/client_vmch/dash/dashboard.html') {
  $WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
  gcloud builds submit "clients/client_vmch/dash" --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
  gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
    --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=vmch.json" `
    --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
    --memory 512Mi --project $PROJECT; Must "deploy dash service"
  gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
  $URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)')
  Write-Host "`n============================================================"
  Write-Host "  DONE. Dashboard is live (password-gated):"
  Write-Host "    $URL"
  Write-Host "============================================================"
} else {
  Write-Host "  SKIPPED dash service - dashboard.html not found."
}