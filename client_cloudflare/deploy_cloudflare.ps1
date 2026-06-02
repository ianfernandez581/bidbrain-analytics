# deploy_cloudflare.ps1 - Windows/PowerShell equivalent of deploy_cloudflare.sh.
#
# Stands up the entire client_cloudflare pipeline on GCP. Run it ONCE. It is
# idempotent: safe to re-run - anything that already exists is left alone, so if
# a step fails you can fix the cause and run it again.
#
#   HOW TO RUN (from this same PowerShell window):
#       .\deploy_cloudflare.ps1
#   If you get "running scripts is disabled on this system", run this first:
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
#   It uses gcloud, bq and git only - your .venv is not needed.
#   You can run it from the repo root OR from inside client_cloudflare\
#   (it relocates itself to the repo root automatically).
#
#   PREREQS:
#     - gcloud + bq installed and authenticated (gcloud auth login), Owner/Editor.
#     - The shared Snowflake key secret 'snowflake-bq-key' already exists (same
#       one MongoDB uses). The script warns if it doesn't.
#     - For the DASHBOARD step only: client_cloudflare\dash\dashboard.html must
#       exist (build it from your index.html per dash\DASHBOARD.md). If it isn't
#       there, everything else still deploys and that one step is skipped.

# ---- config (matches job/main.py + the cloudbuild.yaml files) ---------------
$PROJECT             = "bidbrain-analytics"
$REGION              = "australia-southeast1"
$REPO                = "bidbrain"                 # Artifact Registry docker repo (shared with MongoDB)
$DATASET             = "client_cloudflare"
$BUCKET              = "bidbrain-analytics-cloudflare-dash"
$JOB                 = "cloudflare-export"        # Cloud Run JOB     (= job/cloudbuild.yaml  _JOB)
$SERVICE             = "cloudflare-dash"          # Cloud Run SERVICE (= dash/cloudbuild.yaml _SERVICE)
$JOB_SA              = "cloudflare-dash-job@${PROJECT}.iam.gserviceaccount.com"
$WEB_SA              = "cloudflare-dash-web@${PROJECT}.iam.gserviceaccount.com"
$SNOWFLAKE_SECRET    = "snowflake-bq-key"         # shared, must already exist
$PW_SECRET           = "cloudflare-dash-password"
$SESSION_SECRET_NAME = "cloudflare-dash-session-key"
$SCHEDULE_UTC        = "0 22 * * *"               # 22:00 UTC daily - same time the old Snowflake tasks ran
$REPO_OWNER          = "Bidbrain"
$REPO_NAME           = "bidbrain-analytics"

# ---- helpers ----------------------------------------------------------------
function Die($msg)  { Write-Host "!! Failed: $msg. Fix the cause and re-run (the script is idempotent)." -ForegroundColor Red; exit 1 }
function Must($msg) { if ($LASTEXITCODE -ne 0) { Die $msg } }   # call right after a native command
function Exists($scriptblock) { & $scriptblock *> $null; return ($LASTEXITCODE -eq 0) }

# ---- guards -----------------------------------------------------------------
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found (install the Google Cloud SDK)."; exit 1 }
if (-not (Get-Command bq     -ErrorAction SilentlyContinue)) { Write-Error "bq not found (ships with the Google Cloud SDK)."; exit 1 }

# Build context for `gcloud builds submit .` must be the repo root. If we're sat
# inside client_cloudflare\, step up one level automatically.
if (-not (Test-Path 'client_cloudflare/job/cloudbuild.yaml')) {
  if ((Test-Path 'job/cloudbuild.yaml') -and ((Split-Path -Leaf (Get-Location)) -eq 'client_cloudflare')) {
    Set-Location ..
    Write-Host "Moved up to repo root: $(Get-Location)"
  } else {
    Write-Error "Run this from the repo root (the folder containing client_cloudflare\) or from inside client_cloudflare\."
    exit 1
  }
}

Write-Host "Deploying client_cloudflare to $PROJECT ($REGION)`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/8] Enabling APIs ..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com bigquery.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com --project $PROJECT
Must "enable APIs"

# ---- 2. Artifact Registry, bucket, dataset ----------------------------------
Write-Host "[2/8] Artifact Registry, bucket, dataset ..."
if (Exists { gcloud artifacts repositories describe $REPO --location $REGION --project $PROJECT }) {
  Write-Host "  AR repo $REPO already exists."
} else {
  gcloud artifacts repositories create $REPO --repository-format=docker --location $REGION --project $PROJECT; Must "create AR repo"
}

if (Exists { gcloud storage buckets describe "gs://${BUCKET}" --project $PROJECT }) {
  Write-Host "  Bucket gs://${BUCKET} already exists."
} else {
  gcloud storage buckets create "gs://${BUCKET}" --project $PROJECT --location $REGION --uniform-bucket-level-access; Must "create bucket"
}

if (Exists { bq --project_id=$PROJECT show --dataset "${PROJECT}:${DATASET}" }) {
  Write-Host "  Dataset $DATASET already exists."
} else {
  bq --location=$REGION --project_id=$PROJECT mk --dataset "${PROJECT}:${DATASET}"; Must "create dataset"
}

# ---- 3. Service accounts + IAM (least privilege) ----------------------------
Write-Host "[3/8] Service accounts + IAM ..."
function Ensure-Sa($email, $display) {
  $id = $email.Split('@')[0]
  if (Exists { gcloud iam service-accounts describe $email --project $PROJECT }) {
    Write-Host "  SA $email already exists."
  } else {
    gcloud iam service-accounts create $id --display-name $display --project $PROJECT; Must "create SA $email"
  }
}
Ensure-Sa $JOB_SA "Cloudflare dashboard export job"
Ensure-Sa $WEB_SA "Cloudflare dashboard web service"

# JOB SA: run BigQuery jobs (project-scoped role), edit only its own dataset,
# write the data bucket, read the Snowflake key.
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.jobUser" --condition=None | Out-Null
Must "grant bigquery.jobUser"

# Prefer a dataset-scoped dataEditor grant; fall back to project-scoped only if
# the dataset-level call isn't available, so we never over-grant.
if (Exists { bq add-iam-policy-binding --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataEditor" "${PROJECT}:${DATASET}" }) {
  Write-Host "  dataEditor granted on dataset $DATASET (scoped)."
} else {
  Write-Host "  dataset-scoped grant unavailable; using project-scoped dataEditor."
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/bigquery.dataEditor" --condition=None | Out-Null
  Must "grant bigquery.dataEditor (project)"
}

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${JOB_SA}" --role="roles/storage.objectAdmin" | Out-Null
Must "grant storage.objectAdmin to job SA"
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${WEB_SA}" --role="roles/storage.objectViewer" | Out-Null
Must "grant storage.objectViewer to web SA"

# ---- 4. Secrets -------------------------------------------------------------
Write-Host "[4/8] Secrets ..."
function New-SecretFromValue($name, $value) {
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $value, (New-Object System.Text.UTF8Encoding($false)))  # UTF-8, no BOM, no trailing newline
    gcloud secrets create $name --data-file="$($tmp.FullName)" --project $PROJECT; Must "create secret $name"
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
}

if (Exists { gcloud secrets describe $PW_SECRET --project $PROJECT }) {
  Write-Host "  Secret $PW_SECRET already exists (value left unchanged)."
} else {
  $pw = $env:DASH_PASSWORD
  if ([string]::IsNullOrEmpty($pw)) {
    $secure = Read-Host "  Choose the dashboard password (viewers type this to log in)" -AsSecureString
    $pw = [System.Net.NetworkCredential]::new('', $secure).Password
  }
  New-SecretFromValue $PW_SECRET $pw
}

if (Exists { gcloud secrets describe $SESSION_SECRET_NAME --project $PROJECT }) {
  Write-Host "  Secret $SESSION_SECRET_NAME already exists."
} else {
  $bytes = New-Object byte[] 48
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  New-SecretFromValue $SESSION_SECRET_NAME ([Convert]::ToBase64String($bytes))
}

if (-not (Exists { gcloud secrets describe $SNOWFLAKE_SECRET --project $PROJECT })) {
  Write-Host "  !! WARNING: secret $SNOWFLAKE_SECRET not found. It's the same key MongoDB uses." -ForegroundColor Yellow
  Write-Host "     The job can't reach Snowflake until it exists. Create/copy it, then re-run." -ForegroundColor Yellow
}

# Secret accessor bindings (secrets must exist first).
gcloud secrets add-iam-policy-binding $SNOWFLAKE_SECRET --member="serviceAccount:${JOB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "  (couldn't bind $SNOWFLAKE_SECRET yet - create the secret, then re-run)" -ForegroundColor Yellow }
gcloud secrets add-iam-policy-binding $PW_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null
Must "bind $PW_SECRET to web SA"
gcloud secrets add-iam-policy-binding $SESSION_SECRET_NAME --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null
Must "bind $SESSION_SECRET_NAME to web SA"

# ---- Cloud Build deploy identity --------------------------------------------
# Let the build deploy Cloud Run and "act as" the runtime SAs. run.admin /
# artifactregistry.writer are almost certainly already present (MongoDB deploys
# the same way) - these are idempotent. The grant that matters is
# serviceAccountUser on the two NEW runtime SAs. Cover both the legacy Cloud
# Build SA and the Compute default SA (which one a manual submit uses depends on
# the project's age); tolerate failures.
$PROJECT_NUMBER = (gcloud projects describe $PROJECT --format='value(projectNumber)'); Must "get project number"
$PROJECT_NUMBER = "$PROJECT_NUMBER".Trim()
$buildSAs   = @("${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com", "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com")
$runtimeSAs = @($JOB_SA, $WEB_SA)
foreach ($b in $buildSAs) {
  foreach ($r in $runtimeSAs) {
    gcloud iam service-accounts add-iam-policy-binding $r --member="serviceAccount:$b" --role="roles/iam.serviceAccountUser" --project $PROJECT *> $null
  }
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$b" --role="roles/run.admin" --condition=None *> $null
  gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$b" --role="roles/artifactregistry.writer" --condition=None *> $null
}

# Manual `gcloud builds submit` does NOT auto-populate $SHORT_SHA (only trigger
# builds do), and the cloudbuild.yaml tags images with it - so pass one. Use the
# real short commit if we're in a git checkout.
$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# ---- 5. Deploy the Cloud Run JOB --------------------------------------------
Write-Host "[5/8] Building + deploying the export job ($JOB) ..."
gcloud builds submit --config client_cloudflare/job/cloudbuild.yaml --substitutions="SHORT_SHA=$SHA" --project $PROJECT .
Must "build + deploy export job"

# ---- 6. Bootstrap (cloud-side; runs the job twice) --------------------------
Write-Host "[6/8] Bootstrapping BigQuery (runs the job twice; the FIRST failure is expected) ..."
Write-Host "  -> first run: lands src_*, then errors on the not-yet-existing views (expected) ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait   # exit code intentionally ignored

if (-not (Exists { bq --project_id=$PROJECT show "${PROJECT}:${DATASET}.src_paid_media" })) {
  Write-Host "!! src_* tables were not created - the first run failed BEFORE reaching BigQuery" -ForegroundColor Red
  Write-Host "   (most likely Snowflake auth / the $SNOWFLAKE_SECRET secret). Check the logs:" -ForegroundColor Red
  Write-Host "   gcloud run jobs executions list --job $JOB --region $REGION --project $PROJECT"
  exit 1
}

Write-Host "  -> creating the thin views from client_cloudflare\sql\*.sql ..."
$sqlFiles = Get-ChildItem 'client_cloudflare/sql' -Filter '*.sql' | Sort-Object Name
foreach ($sf in $sqlFiles) {
  Write-Host "     applying $($sf.Name)"
  Get-Content $sf.FullName -Raw | bq query --project_id=$PROJECT --location=$REGION --use_legacy_sql=false *> $null
  Must "apply view $($sf.Name)"
}

Write-Host "  -> second run: writes gs://${BUCKET}/cloudflare.json ..."
gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait
Must "second job run (write cloudflare.json)"

# ---- 7. Daily scheduler (tolerant) ------------------------------------------
Write-Host "[7/8] Daily scheduler ..."
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null
$RUN_JOB_URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if (Exists { gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT }) {
  Write-Host "  Scheduler ${JOB}-daily already exists."
} else {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$SCHEDULE_UTC" --time-zone="UTC" --uri="$RUN_JOB_URI" --http-method=POST --oauth-service-account-email="$JOB_SA" *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "  Created scheduler ${JOB}-daily ($SCHEDULE_UTC UTC)."
  } else {
    Write-Host "  Couldn't create the scheduler automatically. Do it in the console:" -ForegroundColor Yellow
    Write-Host "    Cloud Scheduler -> Create job -> target 'Cloud Run job' -> $JOB, cron '$SCHEDULE_UTC', UTC."
  }
}

# ---- 8. CD triggers (tolerant) ----------------------------------------------
Write-Host "[8/8] CD triggers (push to ^main$) ..."
function New-Trigger($name, $included, $config) {
  if ((Exists { gcloud builds triggers describe $name --region $REGION --project $PROJECT }) -or (Exists { gcloud builds triggers describe $name --project $PROJECT })) {
    Write-Host "  Trigger $name already exists."; return
  }
  gcloud builds triggers create github --name=$name --repo-owner=$REPO_OWNER --repo-name=$REPO_NAME --branch-pattern='^main$' --included-files=$included --build-config=$config --project $PROJECT *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "  Created trigger $name."
  } else {
    Write-Host "  Couldn't create trigger $name automatically (GitHub connection may be 2nd-gen, or it exists)." -ForegroundColor Yellow
    Write-Host "    Create it in the console mirroring your MongoDB trigger: push ^main$, included files '$included', config '$config'."
  }
}
New-Trigger "cloudflare-job-deploy"  "client_cloudflare/job/**"  "client_cloudflare/job/cloudbuild.yaml"
New-Trigger "cloudflare-dash-deploy" "client_cloudflare/dash/**" "client_cloudflare/dash/cloudbuild.yaml"

# ---- Dashboard SERVICE (only if dashboard.html exists) ----------------------
Write-Host ""
if (Test-Path 'client_cloudflare/dash/dashboard.html') {
  Write-Host "Deploying the dashboard service ($SERVICE) ..."
  gcloud builds submit --config client_cloudflare/dash/cloudbuild.yaml --substitutions="SHORT_SHA=$SHA" --project $PROJECT .
  Must "deploy dashboard service"
  $URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
  Write-Host ""
  Write-Host "============================================================"
  Write-Host "  DONE. Dashboard is live (password-gated):"
  Write-Host "    $URL"
  Write-Host ""
  Write-Host "  Final step (manual, in Cloudflare DNS): CNAME cloudflare.bidbrain.ai"
  Write-Host "    -> the *.run.app host above, Proxied, SSL Full (strict),"
  Write-Host "       Host Header Override. See client_cloudflare\dash\LIVE_URL.md."
  Write-Host "============================================================"
} else {
  Write-Host "============================================================"
  Write-Host "  Pipeline + data are deployed; cloudflare.json is in the bucket."
  Write-Host ""
  Write-Host "  SKIPPED the dashboard service - client_cloudflare\dash\dashboard.html"
  Write-Host "  doesn't exist yet. Build it from your index.html (see dash\DASHBOARD.md),"
  Write-Host "  save it into client_cloudflare\dash\, then deploy with:"
  Write-Host ""
  Write-Host "    gcloud builds submit --config client_cloudflare/dash/cloudbuild.yaml --substitutions=SHORT_SHA=manual --project $PROJECT ."
  Write-Host "============================================================"
}
