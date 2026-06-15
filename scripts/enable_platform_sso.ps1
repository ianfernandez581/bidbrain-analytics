# enable_platform_sso.ps1 - wire every client dashboard to trust the platform's SSO cookie.
#
# For each <c>-dash service it: (1) grants the service's runtime SA secretAccessor on the shared
# `platform-sso-key`, and (2) injects SSO_SECRET (from that secret) + CLIENT_KEY=<c> as env. After
# this, a dashboard unlocks for a visitor who arrived via the platform with an agency/dashboard
# password that lists <c> - in ADDITION to its own password (the password always still works).
#
# PREREQUISITES (order matters for SSO to actually take effect end-to-end):
#   1. deploy_platform.ps1 has run (creates `platform-sso-key`).
#   2. Each dashboard has been REBUILT with the new image that contains platform_sso.py + the
#      extended authed() (run clients\client_<c>\dash\deploy_dash_<c>.ps1). Injecting the env here
#      onto an old image is harmless but inert until the new image is deployed.
#   3. Each dashboard is served on <c>.bidbrain.ai (Cloudflare), so the .bidbrain.ai SSO cookie
#      reaches it. On a raw *.run.app host the cookie is never sent and SSO stays inert.
#
#   HOW TO RUN:  .\scripts\enable_platform_sso.ps1
#   Re-runnable; idempotent. Pass -Keys "cityperfume,vmch" to limit to specific dashboards.

param([string]$Keys = "")

$PROJECT = "bidbrain-analytics"
$REGION  = "australia-southeast1"
$SSO_SECRET = "platform-sso-key"

$ALL = @("mongodb","cloudflare","stt","schneider","hireright","cityperfume","resetdata","proptrack","tlm","vmch")
$targets = if ($Keys) { $Keys.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } } else { $ALL }

function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
gcloud secrets describe $SSO_SECRET --project $PROJECT *> $null
if ($LASTEXITCODE -ne 0) { Write-Error "Secret '$SSO_SECRET' not found. Run bidbrain-platform\deploy_platform.ps1 first."; exit 1 }

foreach ($c in $targets) {
  $svc = "$c-dash"
  Write-Host "`n== $svc =="
  $sa = (gcloud run services describe $svc --region $REGION --project $PROJECT --format='value(spec.template.spec.serviceAccountName)' 2>$null)
  $sa = "$sa".Trim()
  if (-not $sa) { Warn "service $svc not found (or no runtime SA) - skipping."; continue }
  Write-Host "  runtime SA: $sa"
  gcloud secrets add-iam-policy-binding $SSO_SECRET --member="serviceAccount:$sa" --role="roles/secretmanager.secretAccessor" --project $PROJECT *> $null
  if ($LASTEXITCODE -ne 0) { Warn "could not bind $SSO_SECRET to $sa"; continue }
  gcloud run services update $svc --region $REGION --project $PROJECT `
    --update-secrets "SSO_SECRET=${SSO_SECRET}:latest" `
    --update-env-vars "CLIENT_KEY=$c" *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  OK: SSO_SECRET + CLIENT_KEY=$c injected (new revision)." }
  else { Warn "update failed for $svc" }
}

Write-Host "`nDone. Reminder: dashboards only honour the SSO cookie once they (a) run the new image"
Write-Host "(deploy_dash_<c>.ps1) and (b) are served on <c>.bidbrain.ai. Their own password always works regardless."
