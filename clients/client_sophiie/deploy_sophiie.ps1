# deploy_sophiie.ps1 - one-shot, idempotent stand-up of the client_sophiie dashboard on GCP.
#
# TWO PHASES:
#   DEFAULT (service only) -> APIs, Artifact Registry, the client bucket, the web service account +
#                             IAM, the two secrets, and the DASH SERVICE. While the bucket holds no
#                             sophiie.json, main.py's /data.json serves the baked-in SAMPLE payload
#                             (dash/placeholder.json) behind the "sample data" banner.
#   -WithData              -> ALSO creates the BigQuery dataset + export-job service account, seeds
#                             the targets, applies the sql/ views, and builds/deploys/runs the
#                             sophiie-export job plus its */10 scheduler. Running the job writes the
#                             real sophiie.json, which AUTOMATICALLY takes over from the placeholder
#                             (main.py prefers the bucket) and the banner clears on its own.
#
# The export job REFUSES to publish an empty fact, so -WithData is safe to run BEFORE the Sophiie AI
# advertiser (Trade Desk id gjcl0pp) is granted to the Windsor Trade Desk connector: it stands the
# pipeline up, finds zero rows, leaves the placeholder in place, and the first */10 tick after real
# rows land publishes for real with no further action. See README.md -> "GO-LIVE".
#
#   HOW TO RUN (from the repo root OR from inside client_sophiie\):
#       .\clients\client_sophiie\deploy_sophiie.ps1              # dash service only
#       .\clients\client_sophiie\deploy_sophiie.ps1 -WithData    # + dataset, views, job, scheduler
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   Deploys need the ian@100.digital account (charles@ has no perms). Pin it for the session:
#       $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
#
#   DATA SOURCE: raw_windsor.perf_the_trade_desk (Windsor TTD connector, self-refreshing via the
#   shared windsor-tradedesk-ingest job). The job SA gets project-scoped roles/bigquery.dataViewer.
param([switch]$WithData)

# ---- config -----------------------------------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$DATASET  = "client_sophiie"
$BUCKET   = "bidbrain-analytics-sophiie-dash"
$JOB      = "sophiie-export"
$SERVICE  = "sophiie-dash"
$JOB_SA   = "sophiie-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA   = "sophiie-dash-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET      = "sophiie-dash-password"
$SESSION_SECRET = "sophiie-dash-session-key"
$SCHEDULE_UTC   = "*/10 * * * *"    # self-gating: every tick probes freshness, rebuilds only on change

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

# A BRAND-NEW service account is not immediately visible to the IAM policy APIs. On the first run of
# this script the create succeeds and the very next add-iam-policy-binding fails with
#   HTTPError 400: Service account sophiie-dash-web@... does not exist
# even though it was just created. That is propagation lag, not a real error - it bit the 2026-08-18
# Sophiie standup and would bite every future new-client standup identically. So every SA-member
# binding goes through this retry instead of a bare Must. Existing-SA re-runs hit it on the first try
# and cost nothing.
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

# Build context is the repo root. If we're inside client_sophiie\, step up.
if (-not (Test-Path 'clients/client_sophiie/dash/Dockerfile')) {
  if ((Test-Path 'dash/Dockerfile') -and ((Split-Path -Leaf (Get-Location)) -eq 'client_sophiie')) {
    Set-Location ../..; Write-Host "Moved up to repo root: $(Get-Location)"
  } else { Write-Error "Run from the repo root or from inside client_sophiie\."; exit 1 }
}

# The repo venv, resolved AFTER the block above has normalised the CWD to the repo root. -WithData
# shells out to it for seed_static.py + create_views.py; without this it was never assigned, so
# Test-Path got $null and the whole data phase died with "repo venv python not found at " (the empty
# path in that message is the tell). Same derivation as clients/client_caltex/deploy_caltex.ps1.
$PYTHON = Join-Path (Get-Location) ".venv\Scripts\python.exe"

Write-Host "Deploying client_sophiie to $PROJECT ($REGION)  [mode: $(if($WithData){'full pipeline'}else{'dash service only'})]`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/5] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry + bucket (+ dataset under -WithData) --------------
Write-Host "[2/5] Artifact Registry + bucket ..."
if (-not (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT })) {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}
# Holds sophiie.json (written by the export job) + the job's _freshness.json watermark. Created
# EMPTY; while it stays empty the service serves its baked-in sample payload.
if (-not (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT })) {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}
if ($WithData) {
  if (-not (Get-Command bq -ErrorAction SilentlyContinue)) { Die "bq not found (needed for -WithData)" }
  if (-not (Exists { bq --project_id=$PROJECT show --dataset "${PROJECT}:${DATASET}" })) {
    bq --location=$REGION --project_id=$PROJECT mk --dataset "${PROJECT}:${DATASET}"; Must "create dataset"
  }
}

# ---- 3. Service accounts + IAM + secrets ------------------------------------
Write-Host "[3/5] Service accounts, IAM + secrets ..."
if (-not (Exists { gcloud iam service-accounts describe $WEB_SA --project $PROJECT })) {
  gcloud iam service-accounts create ($WEB_SA.Split('@')[0]) --display-name "Sophiie AI dashboard web service" --project $PROJECT; Must "create web SA"
}
MustRetry "grant objectViewer to web SA" { gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" }
if ($WithData) {
  # JOB SA: run BigQuery jobs, read across BigQuery (the views read raw_windsor), write the bucket,
  # and own objects in its own dataset (create_views.py runs as the deploying human, but a future
  # materialised table would be written by this identity).
  if (-not (Exists { gcloud iam service-accounts describe $JOB_SA --project $PROJECT })) {
    gcloud iam service-accounts create ($JOB_SA.Split('@')[0]) --display-name "Sophiie AI dashboard export job" --project $PROJECT; Must "create job SA"
  }
  MustRetry "grant jobUser to job SA"     { gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser"    --condition=None }
  MustRetry "grant dataViewer to job SA"  { gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataViewer"  --condition=None }
  MustRetry "grant objectAdmin to job SA" { gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin" }
}

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
MustRetry "bind $PW_SECRET to web SA" { gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT }
MustRetry "bind $SESSION_SECRET to web SA" { gcloud secrets add-iam-policy-binding $SESSION_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT }

# The PLATFORM also needs to read this dashboard's password. dashboards.bidbrain.ai proxies the
# dashboard at /d/sophiie/ and logs into the upstream ON THE USER'S BEHALF (main.py
# _upstream_pw -> _upstream_login), so without secretAccessor for platform-dash-web@ the tile's
# "Open preview ->" button 500s with PermissionDenied on secretmanager.versions.access - which is
# EXACTLY what happened on the 2026-08-08 Geyer Valmont standup, which is why it is baked in here
# rather than granted out-of-band. Do not drop it: without it the portal tile's "Open preview ->"
# returns a bare 500 and NOTHING appears in this service's own logs, because the request never
# reaches this service.
# secretVersionAdder + serviceAccountUser are the super-admin god-mode pair (reveal/rotate the
# password, open any dashboard) - scripts/enable_super_admin.ps1 grants these for its own $CLIENTS
# list, and sophiie is in it, but granting here too keeps this script self-contained.
$PLATFORM_SA = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretAccessor"    --project $PROJECT | Out-Null; Must "bind $PW_SECRET to the platform SA (proxy login)"
gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${PLATFORM_SA}" --role="roles/secretmanager.secretVersionAdder" --project $PROJECT | Out-Null; Must "bind $PW_SECRET rotate to the platform SA"
MustRetry "grant the platform SA actAs on the web SA" { gcloud iam service-accounts add-iam-policy-binding $WEB_SA --member="serviceAccount:${PLATFORM_SA}" --role="roles/iam.serviceAccountUser" --project $PROJECT }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 4. Dashboard service ---------------------------------------------------
Write-Host "[4/5] Dashboard service ..."
$WEB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"
gcloud builds submit clients/client_sophiie/dash --tag $WEB_IMG --region $REGION --project $PROJECT; Must "build dash image"
gcloud run deploy $SERVICE --image $WEB_IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=sophiie.json" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --no-allow-unauthenticated --quiet --project $PROJECT; Must "deploy dash service"
# Org enforces Domain Restricted Sharing, so --allow-unauthenticated is rejected; the app does its
# own password auth, so remove the conflicting invoker gate. Idempotent.
gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()

# ---- 5. (optional) data pipeline: seeds + views + job + scheduler -----------
if ($WithData) {
  Write-Host "[5/5] Data pipeline (seeds + views + export job + scheduler) ..."
  if (-not (Test-Path $PYTHON)) { Die "repo venv python not found at $PYTHON (needed to seed + apply views)" }
  & $PYTHON clients/client_sophiie/seed_static.py;  Must "seed targets/budget"
  & $PYTHON clients/client_sophiie/create_views.py; Must "apply views (raw_windsor.perf_the_trade_desk must exist)"
  $JOB_IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"
  gcloud builds submit clients/client_sophiie/job --tag $JOB_IMG --region $REGION --project $PROJECT; Must "build export job image"
  gcloud run jobs deploy $JOB --image $JOB_IMG --region $REGION --service-account $JOB_SA --memory 1Gi --project $PROJECT; Must "deploy export job"
  # FORCE_REBUILD so the very first run cannot be skipped by the freshness gate. The job exits 0
  # WITHOUT uploading if the fact is still empty (no Windsor grant yet), which is the intended path.
  gcloud run jobs execute $JOB --region $REGION --project $PROJECT --update-env-vars FORCE_REBUILD=1 --wait; Must "run export job"
  $PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)'); $PNUM = "$PNUM".Trim()
  gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
  gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
  $URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
  if (-not (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT })) {
    gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)." } else { Write-Host "  Create the scheduler manually if needed." -ForegroundColor Yellow }
  }
} else {
  Write-Host "[5/5] Data pipeline SKIPPED (dash service only). Re-run with -WithData to stand it up."
}

Write-Host "`n============================================================"
Write-Host "  DONE. Sophiie AI dashboard is live (password-gated):"
Write-Host "    $URL"
if ($WithData) {
  Write-Host "  Pipeline stood up. If the job reported an EMPTY fact, the Sophiie AI advertiser"
  Write-Host "  (gjcl0pp) is not granted to the Windsor Trade Desk connector yet - grant it at"
  Write-Host "  https://onboard.windsor.ai?datasource=tradedesk and the next */10 tick goes live."
} else {
  Write-Host "  Serving the SAMPLE payload until the pipeline is stood up (re-run with -WithData)."
}
Write-Host "  Portal tile: run bidbrain-platform\dash\set_sophiie_tile.py --yes"
Write-Host "============================================================"
