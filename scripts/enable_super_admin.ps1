# enable_super_admin.ps1 - grant the platform front-door the god-mode powers the SUPER ADMIN needs,
# and inject the bootstrap super-admin password. Idempotent; safe to re-run.
#
# The super-admin console (in bidbrain-platform) can REVEAL every password and ROTATE any of them.
# Revealing + rotating the agency/admin passwords needs nothing extra (registry-owned). Rotating a
# DASHBOARD password is true god-mode: it writes a new <c>-dash-password secret version AND restarts
# that <c>-dash service so the new password takes effect everywhere. That needs three grants on the
# platform web SA (platform-dash-web@) that it does NOT have by default:
#   1. secretmanager.secretVersionAdder  on each <c>-dash-password   (add a new secret version)
#   2. run.developer                     (project)                   (create a new <c>-dash revision)
#   3. iam.serviceAccountUser            on each <c>-dash runtime SA  (actAs, required to deploy)
# It also creates the bootstrap secret platform-super-admin-password and mounts it as SUPER_ADMIN_PW
# (plus REGION) on the platform service, so the super-admin login works before anyone re-seeds.
#
#   HOW TO RUN (from the repo root). Deploy the NEW platform image FIRST (it carries the console +
#   the google-cloud-run dependency), THEN run this:
#       .\bidbrain-platform\dash\deploy_dash_platform.ps1
#       .\scripts\enable_super_admin.ps1 -SuperPw 'your-strong-password'
#   Omit -SuperPw and a strong RANDOM password is generated and printed once (no committed default -
#   a shipped default would fail OPEN because the env is the login fallback for an unconfigured registry).
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

param(
  [string]$SuperPw = ""          # blank => generate a strong random one (printed once below)
)

$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$PLATFORM  = "platform-dash"
$WEB_SA    = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
$SUPER_SECRET = "platform-super-admin-password"
# Every dashboard whose password the super admin may rotate (skipped gracefully if not deployed).
$CLIENTS = @("mongodb","cloudflare","stt","schneider","hireright","cityperfume","resetdata","proptrack","tlm","vmch",
             "geocon","bellshakespeare","caltex","nextsmile","status")

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

Write-Host "Enabling super-admin god-mode for $WEB_SA`n"

# ---- 1. bootstrap super-admin password secret + accessor + mount on the platform service ----
Write-Host "[1/4] Bootstrap super-admin password secret ..."
$generated = $false
$createdSecret = $false
if (-not (Exists { gcloud secrets describe $SUPER_SECRET --project $PROJECT })) {
  if (-not $SuperPw) {                          # no committed default - generate a strong random one
    $bytes = New-Object byte[] 18
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $SuperPw = ([Convert]::ToBase64String($bytes)) -replace '[+/=]', ''
    $generated = $true
  }
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $SuperPw, (New-Object System.Text.UTF8Encoding($false)))
    gcloud secrets create $SUPER_SECRET --data-file="$($tmp.FullName)" --project $PROJECT; Must "create $SUPER_SECRET"
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
  $createdSecret = $true
  Write-Host "    created $SUPER_SECRET."
} else {
  Write-Host "    $SUPER_SECRET already exists - leaving its value as-is (rotate in the UI, or add a new version by hand)."
}
gcloud secrets add-iam-policy-binding $SUPER_SECRET --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $SUPER_SECRET accessor"
gcloud run services update $PLATFORM --region $REGION --project $PROJECT `
  --update-secrets "SUPER_ADMIN_PW=${SUPER_SECRET}:latest" --update-env-vars "REGION=${REGION}" | Out-Null; Must "mount SUPER_ADMIN_PW on $PLATFORM"

# ---- 2. project-level run.developer (create new <c>-dash revisions on rotation) ----
Write-Host "[2/4] Granting run.developer (project) to the platform SA ..."
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${WEB_SA}" --role="roles/run.developer" --condition=None | Out-Null; Must "grant run.developer"

# ---- 3. per-dashboard: secretVersionAdder on its password + actAs on its runtime SA ----
Write-Host "[3/4] Per-dashboard grants (secretVersionAdder + serviceAccountUser) ..."
foreach ($c in $CLIENTS) {
  $secret = "$c-dash-password"
  if (Exists { gcloud secrets describe $secret --project $PROJECT }) {
    gcloud secrets add-iam-policy-binding $secret --member="serviceAccount:${WEB_SA}" --role="roles/secretmanager.secretVersionAdder" --project $PROJECT | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Host "    $secret  -> secretVersionAdder" } else { Write-Host "    $secret  -> FAILED (continuing)" -ForegroundColor Yellow }
  } else { Write-Host "    $secret  -> skipped (no such secret)" -ForegroundColor DarkGray }

  # Look up the service's ACTUAL runtime SA (naming differs for some, e.g. vmch/status), then actAs on it.
  $svc = "$c-dash"
  if (Exists { gcloud run services describe $svc --region $REGION --project $PROJECT }) {
    $runtimeSa = (gcloud run services describe $svc --region $REGION --project $PROJECT --format='value(spec.template.spec.serviceAccountName)'); $runtimeSa = "$runtimeSa".Trim()
    if ($runtimeSa) {
      gcloud iam service-accounts add-iam-policy-binding $runtimeSa --member="serviceAccount:${WEB_SA}" --role="roles/iam.serviceAccountUser" --project $PROJECT | Out-Null
      if ($LASTEXITCODE -eq 0) { Write-Host "    $svc      -> actAs $runtimeSa" } else { Write-Host "    $svc      -> actAs FAILED (continuing)" -ForegroundColor Yellow }
    } else { Write-Host "    $svc      -> uses the default compute SA; grant actAs on it by hand if rotation fails" -ForegroundColor Yellow }
  } else { Write-Host "    $svc      -> skipped (service not deployed)" -ForegroundColor DarkGray }
}

# ---- 4. done ----
Write-Host "`n[4/4] Done."
Write-Host "============================================================"
Write-Host "  Super-admin god-mode is enabled."
if ($createdSecret) {
  Write-Host "  Log in at the platform with the super-admin password:" -ForegroundColor Green
  if ($generated) {
    Write-Host "      $SuperPw" -ForegroundColor Yellow
    Write-Host "  ^ GENERATED just now - SAVE IT NOW (it is not stored anywhere you can read back)." -ForegroundColor Yellow
  } else {
    Write-Host "      (the -SuperPw you passed)"
  }
  Write-Host "  Change it any time in the console; that moves it into the registry and supersedes this secret."
} else {
  Write-Host "  $SUPER_SECRET already existed - use its current value, or set a new super-admin password in the console."
}
Write-Host "  The console reveals every agency/dashboard/admin password and rotates any of them."
Write-Host "  NOTE: deploy the platform image that contains the console FIRST if you haven't:"
Write-Host "      .\bidbrain-platform\dash\deploy_dash_platform.ps1"
Write-Host "============================================================"
