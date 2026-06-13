# deploy_ingest_jobs.ps1 — build, deploy & schedule the shared INGEST Cloud Run jobs.
#
# These are the raw-layer loaders that feed EVERY client dashboard. They replace the old
# "run the loader from a laptop" step: each lands data in a shared raw_* BigQuery dataset on
# a daily Cloud Scheduler trigger, staggered BEFORE the 22:00 UTC *-export jobs so every
# dashboard's nightly export reads fresh raw data.
#
#   raw_neto.orders                  <- neto-orders-ingest        (City Perfume sales truth)
#   raw_windsor.perf_meta            <- windsor-meta-ingest       (Meta, all granted accounts)
#   raw_windsor.perf_the_trade_desk  <- windsor-tradedesk-ingest  (TTD, per-account + self-heal)
#   raw_snowflake.*                  <- snowflake-ingest          (Salesforce/TTD/GA/etc, all clients)
#
# (Google Ads + GA4 are NOT here — they auto-refresh daily via BigQuery Data Transfer Service.)
#
# Idempotent. Run as yourself (gcloud authed; build & deploy as yourself — never cloudbuild
# from a laptop). Mirrors the per-client deploy_job_*.ps1 pattern.
#
#   .\scripts\deploy_ingest_jobs.ps1                 # build + deploy + (re)schedule all 4
#   .\scripts\deploy_ingest_jobs.ps1 -Only neto      # just one: neto|meta|tradedesk|snowflake
#   .\scripts\deploy_ingest_jobs.ps1 -SkipBuild      # redeploy + reschedule without rebuilding
#   .\scripts\deploy_ingest_jobs.ps1 -Run            # also execute each job once after deploy
#
param([string]$Only = "", [switch]$SkipBuild, [switch]$Run)

$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$REPO    = "bidbrain"
$SA      = "ingest-runner@$PROJECT.iam.gserviceaccount.com"
$PNUM    = "516554645957"
$SCHED_AGENT = "service-$PNUM@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

function Die($m)  { Write-Host "!! Failed: $m" -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

$SHA = $null
try { $SHA = (& git rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

# key -> build-context dir, Cloud Run job name, memory, cpu, cron (UTC).
# snowflake-ingest is SELF-GATING (per-table freshness gate in loader.py), so it runs */10
# and most ticks are a ~3s no-op; the rest stay daily, just before the 22:00 client exports.
$JOBS = @(
  @{ key="snowflake"; dir="ingest/snowflake_data_pull";         job="snowflake-ingest";         mem="4Gi"; cpu="2"; cron="*/10 * * * *" },
  @{ key="neto";      dir="ingest/neto_data_pull/orders";       job="neto-orders-ingest";       mem="1Gi"; cpu="1"; cron="0 21 * * *"  },
  @{ key="meta";      dir="ingest/windsor_data_pull/meta";      job="windsor-meta-ingest";      mem="1Gi"; cpu="1"; cron="15 21 * * *" },
  @{ key="tradedesk"; dir="ingest/windsor_data_pull/tradedesk"; job="windsor-tradedesk-ingest"; mem="1Gi"; cpu="1"; cron="35 21 * * *" }
)

# ---- one-time shared service account + least-privilege IAM (idempotent) --------------
Write-Host "Ensuring ingest-runner SA + IAM ..."
gcloud iam service-accounts describe $SA --project $PROJECT *> $null
if ($LASTEXITCODE -ne 0) {
  gcloud iam service-accounts create ingest-runner `
    --display-name="Shared ingest loader runner (Neto/Windsor/Snowflake -> raw_*)" --project $PROJECT; Must "create SA"
}
foreach ($s in @("neto-api-key", "windsor-api-key", "snowflake-bq-key")) {
  gcloud secrets add-iam-policy-binding $s --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null
}
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.dataEditor" --condition=None *> $null
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/bigquery.jobUser"   --condition=None *> $null
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-staging --member="serviceAccount:$SA" --role="roles/storage.objectAdmin" *> $null
gcloud iam service-accounts add-iam-policy-binding $SA --member="serviceAccount:$SCHED_AGENT" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null

foreach ($j in $JOBS) {
  if ($Only -and $j.key -ne $Only) { continue }
  $img = "$REGION-docker.pkg.dev/$PROJECT/$REPO/$($j.job):$SHA"

  if (-not $SkipBuild) {
    Write-Host "`n[$($j.key)] Building $img ..."
    gcloud builds submit $j.dir --tag $img --region $REGION --project $PROJECT; Must "build $($j.key)"
  }

  Write-Host "[$($j.key)] Deploying Cloud Run job $($j.job) ..."
  gcloud run jobs deploy $j.job --image $img --region $REGION --project $PROJECT `
    --service-account $SA --memory $j.mem --cpu $j.cpu --task-timeout 3600 --max-retries 1; Must "deploy $($j.key)"

  # daily scheduler (create-or-update) + let the SA invoke the job
  gcloud run jobs add-iam-policy-binding $j.job --region $REGION --project $PROJECT `
    --member="serviceAccount:$SA" --role="roles/run.invoker" *> $null
  $uri = "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/$($j.job):run"
  gcloud scheduler jobs describe "$($j.job)-daily" --location $REGION --project $PROJECT *> $null
  if ($LASTEXITCODE -eq 0) {
    gcloud scheduler jobs update http "$($j.job)-daily" --location $REGION --project $PROJECT --schedule="$($j.cron)" --time-zone="UTC"; Must "update scheduler $($j.key)"
  } else {
    gcloud scheduler jobs create http "$($j.job)-daily" --location $REGION --project $PROJECT `
      --schedule="$($j.cron)" --time-zone="UTC" --uri="$uri" --http-method=POST --oauth-service-account-email="$SA"; Must "create scheduler $($j.key)"
  }
  Write-Host "[$($j.key)] Scheduled '$($j.cron)' UTC."

  if ($Run) { Write-Host "[$($j.key)] Executing once ..."; gcloud run jobs execute $j.job --region $REGION --project $PROJECT --wait }
}

Write-Host "`nDONE. Ingest jobs built, deployed, and scheduled (UTC). snowflake-ingest self-gates at */10 (most ticks no-op); neto/windsor stay daily before the exports."
Write-Host "NOTE: windsor-tradedesk-ingest will exit non-zero until the TTD connector is re-granted"
Write-Host "      at https://onboard.windsor.ai?datasource=tradedesk (Windsor data endpoint is currently down)."
