# Wire the TLM export daily scheduler (one-time).
# Runs tlm-export every 10 minutes, self-gated (the job itself skips
# the rebuild unless upstream raw tables have advanced).
$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$JOB     = "tlm-export"
$SA      = "tlm-dash-job@$PROJECT.iam.gserviceaccount.com"

# Check if the scheduler already exists
$existing = gcloud scheduler jobs describe "${JOB}-daily" --location=$REGION --project=$PROJECT 2>$null
if ($existing) {
  Write-Host "Scheduler ${JOB}-daily already exists — skipping."
  exit 0
}

gcloud scheduler jobs create http "${JOB}-daily" `
  --location=$REGION `
  --schedule="*/10 * * * *" `
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/${JOB}:run" `
  --http-method=POST `
  --oauth-service-account-email=$SA `
  --project=$PROJECT

Write-Host "Scheduler ${JOB}-daily created (runs every 10 min)."