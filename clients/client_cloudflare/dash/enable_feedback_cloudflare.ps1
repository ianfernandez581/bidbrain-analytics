# enable_feedback_cloudflare.ps1 - ONE-TIME standup for the Feedback pill on DIRECT logins to the
# Cloudflare dashboard (dash/feedback_widget.py).
#
# Background: dashboards.bidbrain.ai injects a Feedback pill into every dashboard it proxies, so
# anyone coming through the front-door has always had one. Cloudflare's own people mostly open this
# service DIRECTLY on its run.app URL (their office network does not resolve dashboards.bidbrain.ai),
# and a direct hit never passes through that proxy - so they had no way to send feedback. The
# service now carries its own pill, and this script gives it the one thing it needs: permission to
# write into the PLATFORM's bucket, where the existing feedback tracker reads from.
#
# What it does (idempotent - safe to re-run):
#   1. grants the cloudflare-dash runtime SA roles/storage.objectCreator on the platform bucket
#      (create-only ON PURPOSE: without storage.objects.delete this SA cannot overwrite anything
#      already in that bucket - not the registry, not another client's notes - and every feedback
#      object it writes has a fresh unique name, so it never needs to);
#   2. sets PLATFORM_BUCKET on the cloudflare-dash service, which is the switch that makes the pill
#      appear at all (unset => no pill and the /feedback route 503s, so the button can never be
#      shown without somewhere to store what it collects).
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       .\clients\client_cloudflare\dash\enable_feedback_cloudflare.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# After this runs once, redeploy the image normally with deploy_dash_cloudflare.ps1 - the env var
# persists across image swaps. Notes land in the tracker at dashboards.bidbrain.ai/feedback/admin,
# tagged user_kind "client-direct" so you can tell a direct submission from a front-door one.

$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$SERVICE = "cloudflare-dash"
$SA      = "cloudflare-dash-web@bidbrain-analytics.iam.gserviceaccount.com"   # dash runtime SA
$BUCKET  = "bidbrain-analytics-platform-dash"   # the PLATFORM bucket - feedback/<client>/... lives here

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "granting storage.objectCreator on gs://$BUCKET to $SA (feedback writes) ..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectCreator" --project $PROJECT | Out-Null; Must "grant bucket object-create"

Write-Host "setting PLATFORM_BUCKET=$BUCKET on $SERVICE ..."
gcloud run services update $SERVICE --region $REGION --project $PROJECT --update-env-vars "PLATFORM_BUCKET=$BUCKET"; Must "update service"

$URL = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. The Feedback pill is live for direct logins at:" -ForegroundColor Green
Write-Host "    $URL"
Write-Host "Notes appear at https://dashboards.bidbrain.ai/feedback/admin (client: cloudflare)."
Write-Host "It stays hidden behind the front-door (/d/cloudflare/) - the proxy injects its own there."
