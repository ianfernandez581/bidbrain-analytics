# enable_google_signin.ps1 - turn ON "Log in with Google" for the platform front-door. Idempotent.
#
# Google sign-in is a PARALLEL login to the password gate (the password gate is untouched). It is
# OFF until the platform service has a Google client id + secret in its environment. This script:
#   1. stores the OAuth client id + secret in Secret Manager (platform-google-client-id / -secret),
#   2. grants the platform web SA (platform-dash-web@) secretAccessor on both,
#   3. mounts them as GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (+ sets OAUTH_REDIRECT_BASE) on the
#      platform-dash service, which flips GOOGLE_ENABLED on in main.py.
#
# BEFORE running, in the Google Cloud Console (APIs & Services -> Credentials), create an OAuth 2.0
# Client ID of type "Web application" and register this Authorized redirect URI:
#       https://dashboards.bidbrain.ai/auth/google/callback
# (add http://localhost:8080/auth/google/callback too if you sign in locally). Configure the OAuth
# consent screen (External; scopes openid/email/profile - all non-sensitive). Copy the client id +
# secret it issues and pass them below.
#
#   HOW TO RUN (from the repo root). Deploy the NEW platform image FIRST (it carries Authlib + the
#   routes), THEN run this so the secret-mount revision uses that image:
#       .\bidbrain-platform\dash\deploy_dash_platform.ps1
#       .\scripts\enable_google_signin.ps1 -ClientId '<id>.apps.googleusercontent.com' -ClientSecret '<secret>'
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

param(
  [Parameter(Mandatory = $true)][string]$ClientId,
  [Parameter(Mandatory = $true)][string]$ClientSecret,
  [string]$RedirectBase = "https://dashboards.bidbrain.ai"   # the public platform origin (no trailing slash)
)

$PROJECT   = "bidbrain-analytics"
$REGION    = "australia-southeast1"
$PLATFORM  = "platform-dash"
$WEB_SA    = "platform-dash-web@${PROJECT}.iam.gserviceaccount.com"
$ID_SECRET     = "platform-google-client-id"
$SECRET_SECRET = "platform-google-client-secret"

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

# Create-or-add-version a secret from a literal value (UTF-8, no BOM, no trailing newline).
function Set-Secret($name, $value) {
  $tmp = New-TemporaryFile
  try {
    [System.IO.File]::WriteAllText($tmp.FullName, $value, (New-Object System.Text.UTF8Encoding($false)))
    if (Exists { gcloud secrets describe $name --project $PROJECT }) {
      gcloud secrets versions add $name --data-file="$($tmp.FullName)" --project $PROJECT | Out-Null; Must "add version to $name"
      Write-Host "    $name -> new version added"
    } else {
      gcloud secrets create $name --data-file="$($tmp.FullName)" --project $PROJECT | Out-Null; Must "create $name"
      Write-Host "    $name -> created"
    }
  } finally { Remove-Item $tmp.FullName -Force -ErrorAction SilentlyContinue }
  gcloud secrets add-iam-policy-binding $name --member="serviceAccount:${WEB_SA}" `
    --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "bind $name accessor"
}

Write-Host "Enabling Google sign-in on $PLATFORM`n"

Write-Host "[1/2] Storing OAuth credentials in Secret Manager ..."
Set-Secret $ID_SECRET     $ClientId
Set-Secret $SECRET_SECRET $ClientSecret

Write-Host "[2/2] Mounting credentials on $PLATFORM (new revision; existing env/secrets preserved) ..."
gcloud run services update $PLATFORM --region $REGION --project $PROJECT `
  --update-secrets "GOOGLE_CLIENT_ID=${ID_SECRET}:latest,GOOGLE_CLIENT_SECRET=${SECRET_SECRET}:latest" `
  --update-env-vars "OAUTH_REDIRECT_BASE=${RedirectBase}" | Out-Null; Must "mount Google creds on $PLATFORM"

Write-Host "`n============================================================"
Write-Host "  Google sign-in is ENABLED." -ForegroundColor Green
Write-Host "  Make sure this redirect URI is registered on the OAuth client:"
Write-Host "      ${RedirectBase}/auth/google/callback"
Write-Host "  Authorise sign-ins by mapping emails to roles: config.GOOGLE_ALLOWLIST (seed) or the"
Write-Host "  admin UI (live). An email not on the allow-list is denied after a successful Google login."
Write-Host "============================================================"
