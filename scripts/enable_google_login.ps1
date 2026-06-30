# enable_google_login.ps1 - switch on native "Sign in with Google" on the platform front-door.
# Idempotent; safe to re-run (just re-sets the env var). Password login is unaffected either way.
#
# Google login is an ADDITIVE second path next to the password box: the login page renders Google's
# official button, the browser posts a signed ID token (JWT) to the platform's /auth/google, and the
# platform verifies it against the OAuth *Client ID* below and maps the verified email to a role
# (store.resolve_email). The client id is PUBLIC (it ships in the login HTML) and there is NO client
# secret - so all this script does is inject GOOGLE_OAUTH_CLIENT_ID onto the platform service.
#
# ONE-TIME CONSOLE STEP FIRST (the OAuth client cannot be created with gcloud):
#   1. Console -> APIs & Services -> Credentials -> Create credentials -> OAuth client ID.
#        (If prompted, configure the OAuth consent screen first: Internal user type is fine for a
#         100.digital / Workspace-only audience; otherwise External + add test users.)
#   2. Application type = "Web application".
#   3. Authorized JavaScript origins:  https://dashboards.bidbrain.ai
#        and the raw run URL too, e.g. https://platform-dash-516554645957.australia-southeast1.run.app
#      (No "Authorized redirect URI" is needed - we use the GIS button + a same-origin fetch, not a
#       redirect flow.)
#   4. Copy the generated Client ID (looks like 1234567890-abc...apps.googleusercontent.com).
#
#   THEN run (from anywhere - paths resolve from the repo, not the cwd):
#       .\scripts\enable_google_login.ps1 -ClientId '1234...apps.googleusercontent.com'
#   Deploy the platform image that carries the Google-login code FIRST if you haven't:
#       .\bidbrain-platform\dash\deploy_dash_platform.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# WHO GETS IN: only emails granted access resolve - everyone else is rejected after a valid Google
# sign-in. ian@100.digital is the baked-in super admin (config USERS); assign more accounts (to a
# role, an agency, or a single dashboard) in the super-admin console's "Google sign-in access" panel.

param(
  [Parameter(Mandatory = $true)]
  [string]$ClientId
)

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$PLATFORM = "platform-dash"

function Die($m) { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

$ClientId = "$ClientId".Trim()
if ($ClientId -notmatch 'apps\.googleusercontent\.com$') {
  Write-Host "Warning: '$ClientId' doesn't look like a Google OAuth client id (expected to end in apps.googleusercontent.com)." -ForegroundColor Yellow
}

Write-Host "Setting GOOGLE_OAUTH_CLIENT_ID on $PLATFORM ..."
gcloud run services update $PLATFORM --region $REGION --project $PROJECT `
  --update-env-vars "GOOGLE_OAUTH_CLIENT_ID=$ClientId" | Out-Null; Must "set GOOGLE_OAUTH_CLIENT_ID"

$URL = (gcloud run services describe $PLATFORM --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. Native Google sign-in is now live on the platform login page:" -ForegroundColor Green
Write-Host "    https://dashboards.bidbrain.ai   (also $URL)"
Write-Host "Grant accounts access in the super-admin console -> 'Google sign-in access'."
Write-Host "ian@100.digital is already the baked-in super admin."
