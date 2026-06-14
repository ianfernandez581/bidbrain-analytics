# scheduler.ps1 — set the vmch-export-daily self-gating Cloud Scheduler to */10 UTC.
$PROJECT="bidbrain-analytics"; $REGION="australia-southeast1"
$JOB="vmch-export"; $JOB_SA="${JOB}-job@${PROJECT}.iam.gserviceaccount.com"
$SCHEDULE="*/10 * * * *"

$PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)').Trim()
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT `
  --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA `
  --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" `
  --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null

$URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if (gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT *> $null) {
  gcloud scheduler jobs update http "${JOB}-daily" --location $REGION --project $PROJECT `
    --schedule="$SCHEDULE" --time-zone="UTC" --uri="$URI" --http-method=POST `
    --oauth-service-account-email="$JOB_SA" *> $null
  Write-Host "Updated ${JOB}-daily to ${SCHEDULE} UTC."
} else {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT `
    --schedule="$SCHEDULE" --time-zone="UTC" --uri="$URI" --http-method=POST `
    --oauth-service-account-email="$JOB_SA" *> $null
  Write-Host "Created ${JOB}-daily (${SCHEDULE} UTC)."
}