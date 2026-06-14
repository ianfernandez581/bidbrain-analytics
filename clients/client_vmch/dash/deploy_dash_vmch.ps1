# deploy_dash_vmch.ps1 — rebuild + redeploy the vmch-dash service.
param([string]$SHA = "")
if (-not $SHA) {
  try { $SHA = (git rev-parse --short HEAD 2>$null).Trim() } catch { }
  if (-not $SHA) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
}
$PROJECT="bidbrain-analytics"; $REGION="australia-southeast1"; $REPO="bidbrain"
$SERVICE="vmch-dash"; $BUCKET="bidbrain-analytics-vmch-dash"
$WEB_SA="${SERVICE}-web@${PROJECT}.iam.gserviceaccount.com"
$PW_SECRET="vmch-dash-password"; $SESSION_SECRET="vmch-dash-session-key"
$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${SHA}"

gcloud builds submit $PSScriptRoot --tag $IMG --region $REGION --project $PROJECT
if ($LASTEXITCODE -ne 0) { exit 1 }

gcloud run deploy $SERVICE --image $IMG --region $REGION --service-account $WEB_SA `
  --set-env-vars "GCS_BUCKET=${BUCKET},DATA_OBJECT=vmch.json" `
  --set-secrets "DASH_PASSWORD=${PW_SECRET}:latest,SESSION_SECRET=${SESSION_SECRET}:latest" `
  --memory 512Mi --project $PROJECT
if ($LASTEXITCODE -ne 0) { exit 1 }

gcloud run services update $SERVICE --region $REGION --no-invoker-iam-check --project $PROJECT | Out-Null
$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)')
Write-Host "Done. Service URL: $URL"