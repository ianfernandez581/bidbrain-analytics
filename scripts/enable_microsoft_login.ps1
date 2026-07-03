# enable_microsoft_login.ps1 - switch on native "Sign in with Microsoft" (Teams / M365) on the
# platform front-door. Idempotent; safe to re-run. Password + Google login are unaffected either way.
#
# Microsoft login is an ADDITIVE path next to the password box and the Google button: the login page
# loads MSAL.js and shows a "Sign in with Microsoft" button, the popup returns a signed ID token (JWT),
# the browser posts it to the platform's /auth/microsoft, and the platform verifies it against OUR
# tenant's public signing keys (JWKS) and maps the verified email to a role (store.resolve_email). There
# is NO client secret (public-client model, same as Google) - so this script just injects two env vars:
# MICROSOFT_OAUTH_CLIENT_ID (the app registration's Application/client id) and MICROSOFT_OAUTH_TENANT
# (OUR Directory/tenant id - SINGLE-TENANT so only our own org's accounts can sign in). Both must be set
# for the button to appear.
#
# ONE-TIME CONSOLE STEP FIRST (the app registration can't be created with gcloud):
#   1. Entra admin center (entra.microsoft.com) -> Identity -> Applications -> App registrations
#        -> New registration.
#   2. Supported account types = "Accounts in this organizational directory only" (single tenant).
#   3. Redirect URI: platform = "Single-page application (SPA)", then add BOTH origins:
#        https://dashboards.bidbrain.ai
#        https://platform-dash-516554645957.australia-southeast1.run.app
#      (SPA type is required for the MSAL.js popup; no client secret, no web redirect.)
#   4. On the app's Overview, copy the "Application (client) ID" and the "Directory (tenant) ID".
#        (openid / profile / email are default delegated permissions - no extra API consent needed.)
#
#   THEN run (from anywhere - paths resolve from the repo, not the cwd):
#       .\scripts\enable_microsoft_login.ps1 -ClientId '<application-client-id>' -Tenant '<directory-tenant-id>'
#   Deploy the platform image that carries the Microsoft-login code FIRST if you haven't:
#       .\bidbrain-platform\dash\deploy_dash_platform.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# WHO GETS IN: only emails granted access resolve - everyone else is rejected after a valid Microsoft
# sign-in (same allow-list as Google). A verified @100.digital work/school account auto-becomes admin
# (config.ADMIN_EMAIL_DOMAINS); assign other accounts in the super-admin console's sign-in-access panel.

param(
  [Parameter(Mandatory = $true)]
  [string]$ClientId,
  [Parameter(Mandatory = $true)]
  [string]$Tenant
)

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$PLATFORM = "platform-dash"

function Die($m) { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

$ClientId = "$ClientId".Trim()
$Tenant   = "$Tenant".Trim()
$guidRe = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
if ($ClientId -notmatch $guidRe) {
  Write-Host "Warning: '$ClientId' doesn't look like an Application (client) ID GUID." -ForegroundColor Yellow
}
if ($Tenant -notmatch $guidRe -and $Tenant -notmatch '\.') {
  Write-Host "Warning: '$Tenant' isn't a GUID or a domain - expected the Directory (tenant) ID." -ForegroundColor Yellow
}

Write-Host "Setting MICROSOFT_OAUTH_CLIENT_ID + MICROSOFT_OAUTH_TENANT on $PLATFORM ..."
gcloud run services update $PLATFORM --region $REGION --project $PROJECT `
  --update-env-vars "MICROSOFT_OAUTH_CLIENT_ID=$ClientId,MICROSOFT_OAUTH_TENANT=$Tenant" | Out-Null
Must "set Microsoft OAuth env vars"

$URL = (gcloud run services describe $PLATFORM --region $REGION --project $PROJECT --format='value(status.url)'); $URL = "$URL".Trim()
Write-Host "`nDONE. Native Microsoft sign-in is now live on the platform login page:" -ForegroundColor Green
Write-Host "    https://dashboards.bidbrain.ai   (also $URL)"
Write-Host "Grant accounts access in the super-admin console (same panel as Google)."
Write-Host "A verified @100.digital work/school account auto-becomes admin."
