# Fast-path: rebuild & deploy the TLM dash web app (does NOT provision infra).
# Run from the repo root with the venv active.
#   .\clients\client_tlm\dash\deploy_dash_tlm.ps1
$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$REPO    = "bidbrain"
$SERVICE = "tlm-dash"
$SA      = "tlm-dash-web@$PROJECT.iam.gserviceaccount.com"
$BUCKET  = "bidbrain-analytics-tlm-dash"
$SHORT   = git rev-parse --short HEAD
$IMAGE   = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHORT}"
$DIR     = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Building $IMAGE ..."
gcloud builds submit $DIR --tag=$IMAGE --project=$PROJECT --region=$REGION

Write-Host "Deploying $SERVICE ..."
# NOTE: quote the comma-separated --set-env-vars / --set-secrets values. Bareword
# commas are parsed by PowerShell as the array operator, which mangles the flag and
# makes gcloud crash with "Invalid secret spec". Quoting passes them as one token.
gcloud run deploy $SERVICE --image=$IMAGE --region=$REGION --service-account=$SA "--set-env-vars=GCS_BUCKET=$BUCKET,DATA_OBJECT=tlm.json" "--set-secrets=DASH_PASSWORD=tlm-dash-password:latest,SESSION_SECRET=tlm-dash-session-key:latest" --memory=512Mi --quiet --project=$PROJECT

gcloud run services update $SERVICE --region=$REGION --no-invoker-iam-check --project=$PROJECT

Write-Host "Done: $(gcloud run services describe $SERVICE --region=$REGION --format='value(status.url)' --project=$PROJECT)"