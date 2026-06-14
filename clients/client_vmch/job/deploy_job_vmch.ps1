# deploy_job_vmch.ps1 — build + deploy + execute the vmch-export job.
param([string]$SHA = "")
if (-not $SHA) {
  try { $SHA = (git rev-parse --short HEAD 2>$null).Trim() } catch { }
  if (-not $SHA) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
}
$PROJECT="bidbrain-analytics"; $REGION="australia-southeast1"; $REPO="bidbrain"
$JOB="vmch-export"; $JOB_SA="${JOB}-job@${PROJECT}.iam.gserviceaccount.com"
$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${JOB}:${SHA}"

gcloud builds submit $PSScriptRoot --tag $IMG --region $REGION --project $PROJECT
if ($LASTEXITCODE -ne 0) { exit 1 }

gcloud run jobs deploy $JOB --image $IMG --region $REGION `
  --service-account $JOB_SA --memory 1Gi --project $PROJECT
if ($LASTEXITCODE -ne 0) { exit 1 }

gcloud run jobs execute $JOB --region $REGION --project $PROJECT --wait