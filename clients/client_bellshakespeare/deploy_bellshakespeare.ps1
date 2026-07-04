# deploy_bellshakespeare.ps1 - one-shot, idempotent stand-up of the client_bellshakespeare dashboard on GCP.
#
# TWO PHASES (Bell Shakespeare has no live data connected yet):
#   DEFAULT (placeholder)  -> APIs, Artifact Registry, bucket, dataset, service accounts + IAM,
#                             secrets, and the DASH SERVICE. The bucket is left EMPTY, so the service
#                             serves the baked-in SAMPLE payload (dash/placeholder.json) behind the
#                             "sample data" banner. This is the Monday-onboarding deliverable.
#   -WithData              -> ALSO apply the SQL views + build/deploy/run the export job + scheduler.
#                             Only valid ONCE real Bell Shakespeare Meta data flows into raw_windsor.perf_meta
#                             (campaigns prefixed 'Bell Shakespeare_') AND raw_windsor.bellshakespeare_meta_breakdown
#                             exists (see ingest/meta_breakdown_pull.py). Running the job writes the
#                             real bellshakespeare.json to the bucket, which then AUTOMATICALLY takes over from
#                             the placeholder (main.py /data.json prefers the bucket) and the banner
#                             clears on its own.
#
#   HOW TO RUN (from the repo root OR from inside client_bellshakespeare\):
#       .\clients\client_bellshakespeare\deploy_bellshakespeare.ps1              # placeholder service
#       .\clients\client_bellshakespeare\deploy_bellshakespeare.ps1 -WithData    # full pipeline (once data is connected)
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Deploys need the ian@100.digital account (charles@ has no perms). Pin it for the session:
#       $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
#
#   DATA SOURCE (Phase 2): Bell Shakespeare reads raw_windsor.perf_meta (Windsor, self-refreshing) — same as
#   the geocon template this was cloned from. The job SA gets project-scoped roles/bigquery.dataViewer.

param([switch]$WithData)

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$DATASET  = "client_bellshakespeare"
$BUCKET   = "bidbrain-analytics-bellshakespeare-dash"
$JOB      = "bellshakespeare-export"
$SERVICE  = "bellshakespeare-dash"
$JOB_SA   = "bellshakespeare-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA   = "bellshakespeare-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "bellshakespeare-dash-password"
$SESSION_SECRET = "bellshakespeare-dash-session-key"
$SCHEDULE_UTC   = "*/10 * * * *"        # self-gating: */10 UTC tick, rebuilds only when upstream advanced

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if (-not (Get-Command bq     -ErrorAction SilentlyContinue)) { Write-Error "bq not found."; exit 1 }

# Build context for `gcloud builds submit .` is the repo root. If we're inside client_bellshakespeare\, step up.
if (-not (Test-Path 'clients/client_bellshakespeare/dash/Dockerfile')) {
  if ((Test-Path 'dash/Dockerfile') -and ((Split-Path -Leaf (Get-Location)) -eq 'client_bellshakespeare')) {
    Set-Location ../..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside client_bellshakespeare\."; exit 1 }
}

$PYTHON = Join-Path (Get-Location) ".venv\Scripts\python.exe"

Write-Host "Deploying client_bellshakespeare to $PROJECT ($REGION)  [mode: $(if($WithData){'full pipeline'}else{'placeholder service'})]`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/6] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry, bucket, dataset ----------------------------------
Write-Host "[2/6] Artifact Registry, bucket, dataset ..."
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
Write-Host "[3/6] Service accounts + IAM ..."
function Ensure-Sa($email, $display) {
  $id = $email.Split('@')[0]
  if (-not (Exists { gcloud iam service-accounts describe $email --project $PROJECT })) {
    gcloud iam service-accounts create $id --display-name $display --project $PROJECT; Must "create SA $email"
  }
}
Ensure-Sa $JOB_SA "Bell Shakespeare dashboard export job"
Ensure-Sa $WEB_SA "Bell Shakespeare dashboard web service"

# JOB SA: run BigQuery jobs + read-only across BigQuery (views read raw_windsor), write the data bucket.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser"    --condition=None | Out-Null; Must "grant jobUser"
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataViewer"  --condition=None | Out-Null; Must "grant dataViewer"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin"  | Out-Null; Must "grant objectAdmin to job SA"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" | Out-Null; Must "grant objectViewer to web SA"

# ---- 4. Secrets -------------------------------------------------------------
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

# ---- 5. Dashboard service (serves placeholder.json until real bellshakespeare.json exists) -----------
Write-Host "[5/6] Dashboard service ..."
$WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
gcloud builds submit clients/client_bellshakespeare/dash --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=bellshakespeare.json" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
# Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
# own password auth, so remove the conflicting invoker gate. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()

# ---- 6. (optional) data pipeline: views + job + scheduler -------------------
if ($WithData) {
  Write-Host "[6/6] Data pipeline (views + export job + scheduler) ..."
  if (-not (Test-Path $PYTHON)) { Die "repo venv python not found at $PYTHON (needed to apply views)" }
  & $PYTHON clients/client_bellshakespeare/seed_static.py; Must "seed targets/budget"
  & $PYTHON clients/client_bellshakespeare/create_views.py; Must "apply views (raw_windsor.perf_meta + bellshakespeare_meta_breakdown must exist)"
  $JOB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
  gcloud builds submit clients/client_bellshakespeare/job --tag $JOB_IMG --region $REGION --project $PROJECT; Must "build export job image"
  gcloud run jobs deploy $JOB --image $JOB_IMG --region $REGION --service-account $JOB_SA --memory 1Gi --project $PROJECT; Must "deploy export job"
  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run export job (write bellshakespeare.json)"
  $PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)'); $PNUM = "$PNUM".Trim()
  gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
  gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
  $URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
  if (-not (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT })) {
    gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)." } else { Write-Host "  Create the scheduler manually if needed." -ForegroundColor Yellow }
  }
  Write-Host "  Real bellshakespeare.json written -> the dashboard now shows LIVE data (placeholder banner clears)."
} else {
  Write-Host "[6/6] Data pipeline SKIPPED (placeholder mode). Re-run with -WithData once Bell Shakespeare data is connected."
}

Write-Host "`n============================================================"
Write-Host "  DONE. Bell Shakespeare dashboard is live (password-gated):"
Write-Host "    $URL"
if (-not $WithData) { Write-Host "  Showing SAMPLE data (placeholder banner). Connect data, then re-run with -WithData." }
Write-Host "  Portal tile: run bidbrain-platform\dash\add_bellshakespeare_placeholder.py --yes (or seed_registry)."
Write-Host "============================================================"
