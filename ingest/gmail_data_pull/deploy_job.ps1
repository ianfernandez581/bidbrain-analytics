# Deploy the Gmail -> GCS -> BigQuery GA4 intake job (Schneider's forwarded reports).
# Idempotent. Run as the deploy account (ian@100.digital). Prereq: the Gmail OAuth
# token must already be in Secret Manager as 'schneider-gmail-oauth' (see README /
# gen_gmail_token.py). See CLAUDE.md for the region/project fixed facts.
$ErrorActionPreference = "Stop"

$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$REPO    = "bidbrain"
$JOB     = "gmail-ga4-ingest"
$SA_ID   = "gmail-ga4-ingest"
$SA      = "$SA_ID@$PROJECT.iam.gserviceaccount.com"
$BUCKET  = "bidbrain-analytics-schneider-intake"
$SECRET  = "schneider-gmail-oauth"
$IMG     = "$REGION-docker.pkg.dev/$PROJECT/$REPO/${JOB}:$(git rev-parse --short HEAD)"

Write-Host "== Service account ==" -ForegroundColor Cyan
if (-not (gcloud iam service-accounts describe $SA --project $PROJECT 2>$null)) {
    gcloud iam service-accounts create $SA_ID --project $PROJECT --display-name "Gmail GA4 intake job"
}

Write-Host "== Intake bucket ==" -ForegroundColor Cyan
if (-not (gcloud storage buckets describe "gs://$BUCKET" --project $PROJECT 2>$null)) {
    gcloud storage buckets create "gs://$BUCKET" --project $PROJECT --location $REGION --uniform-bucket-level-access
}

Write-Host "== Secret check ==" -ForegroundColor Cyan
if (-not (gcloud secrets describe $SECRET --project $PROJECT 2>$null)) {
    Write-Warning "Secret '$SECRET' does not exist. Create it from token.json first:"
    Write-Warning "  gcloud secrets create $SECRET --project $PROJECT --data-file=token.json"
    throw "Missing secret $SECRET - generate the token (gen_gmail_token.py) and upload it, then re-run."
}

Write-Host "== IAM ==" -ForegroundColor Cyan
gcloud secrets add-iam-policy-binding $SECRET --project $PROJECT `
    --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor | Out-Null
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" `
    --member "serviceAccount:$SA" --role roles/storage.objectAdmin | Out-Null
gcloud projects add-iam-policy-binding $PROJECT `
    --member "serviceAccount:$SA" --role roles/bigquery.dataEditor --condition=None | Out-Null
gcloud projects add-iam-policy-binding $PROJECT `
    --member "serviceAccount:$SA" --role roles/bigquery.jobUser --condition=None | Out-Null

Write-Host "== Build ==" -ForegroundColor Cyan
gcloud builds submit $PSScriptRoot --tag $IMG --project $PROJECT --region $REGION

Write-Host "== Deploy job ==" -ForegroundColor Cyan
gcloud run jobs deploy $JOB --image $IMG --project $PROJECT --region $REGION `
    --service-account $SA --memory 1Gi --max-retries 1 --task-timeout 900 `
    --set-env-vars "PROJECT=$PROJECT,GMAIL_TOKEN_SECRET=$SECRET,GCS_BUCKET=$BUCKET,GCS_PREFIX=ga4,LOAD_TO_BQ=true,BQ_DATASET=raw_ga4,BQ_TABLE=schneider_ga4_email"

# Let the scheduler's SA invoke the job.
gcloud run jobs add-iam-policy-binding $JOB --project $PROJECT --region $REGION `
    --member "serviceAccount:$SA" --role roles/run.invoker | Out-Null

Write-Host "== Scheduler (every 2h) ==" -ForegroundColor Cyan
$SCHED = "$JOB-2h"
$URI = "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/${JOB}:run"
if (gcloud scheduler jobs describe $SCHED --location $REGION --project $PROJECT 2>$null) {
    gcloud scheduler jobs update http $SCHED --location $REGION --project $PROJECT `
        --schedule "0 */2 * * *" --uri $URI --http-method POST --oauth-service-account-email $SA
} else {
    gcloud scheduler jobs create http $SCHED --location $REGION --project $PROJECT `
        --schedule "0 */2 * * *" --uri $URI --http-method POST --oauth-service-account-email $SA
}

Write-Host "Done. Test it now with:" -ForegroundColor Green
Write-Host "  gcloud run jobs execute $JOB --region $REGION --project $PROJECT" -ForegroundColor Green
