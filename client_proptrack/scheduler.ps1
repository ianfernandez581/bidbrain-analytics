# scheduler.ps1 - (re)create the daily Cloud Scheduler trigger for the PropTrack export job.
#
# deploy_proptrack.ps1 already wires this on first stand-up; this standalone script is for re-creating
# or adjusting the schedule later. Idempotent.
#
#   .\client_proptrack\scheduler.ps1                 # 22:00 UTC daily (default)
#   .\client_proptrack\scheduler.ps1 -Schedule "0 */6 * * *"   # custom cron

param([string]$Schedule = "0 22 * * *")

$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$JOB     = "proptrack-export"
$JOB_SA  = "proptrack-dash-job@${PROJECT}.iam.gserviceaccount.com"

$PNUM = (gcloud projects describe $PROJECT --format='value(projectNumber)'); $PNUM = "$PNUM".Trim()

# The job SA may invoke the job; the Cloud Scheduler service agent may mint tokens as the job SA.
gcloud run jobs add-iam-policy-binding $JOB --region $REGION --project $PROJECT --member="serviceAccount:${JOB_SA}" --role="roles/run.invoker" *> $null
gcloud iam service-accounts add-iam-policy-binding $JOB_SA --member="serviceAccount:service-${PNUM}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator" --project $PROJECT *> $null

$URI = "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
$desc = (gcloud scheduler jobs describe "${JOB}-daily" --location $REGION --project $PROJECT 2>$null)
if ($LASTEXITCODE -eq 0) {
  gcloud scheduler jobs update http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$Schedule" --time-zone="UTC"
  Write-Host "Updated scheduler ${JOB}-daily -> '$Schedule' UTC."
} else {
  gcloud scheduler jobs create http "${JOB}-daily" --location $REGION --project $PROJECT --schedule="$Schedule" --time-zone="UTC" --uri="$URI" --http-method=POST --oauth-service-account-email="$JOB_SA"
  Write-Host "Created scheduler ${JOB}-daily -> '$Schedule' UTC."
}
