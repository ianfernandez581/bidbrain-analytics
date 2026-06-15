# Fast-path: rebuild & deploy the TLM export job (does NOT provision infra).
# Run from the repo root with the venv active.
#   .\clients\client_tlm\job\deploy_job_tlm.ps1
$ErrorActionPreference = "Stop"
$PROJECT= "bidbrain-analytics"
$REGION = "australia-southeast1"
$REPO   = "bidbrain"
$JOB    = "tlm-export"
$SA     = "tlm-dash-job@$PROJECT.iam.gserviceaccount.com"
$SHORT  = git rev-parse --short HEAD
$IMAGE  = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHORT}"
$DIR    = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Building $IMAGE ..."
gcloud builds submit $DIR --tag=$IMAGE --project=$PROJECT --region=$REGION

Write-Host "Deploying $JOB ..."
gcloud run jobs deploy $JOB --image=$IMAGE --region=$REGION --service-account=$SA --memory=1Gi --project=$PROJECT

Write-Host "Done. Run: gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT --update-env-vars FORCE_REBUILD=1 --wait"