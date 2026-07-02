# enable_report_schneider.ps1 - ONE-TIME standup for the portal "Download slides" feature (dash/report.py).
# Grants the schneider-dash runtime SA secret-read on the shared anthropic-api-key (+ optional gemini-api-key)
# and bucket-write (for the report cache), mounts the keys on the schneider-dash service, and bumps the Cloud
# Run request timeout so the two-stage Claude/Gemini call (web research + structuring) can finish. Idempotent.
# The secrets already exist project-wide (created by mongodb's enable script), so this mostly just grants IAM +
# mounts + bumps the timeout; re-supplying the same -Key/-GeminiKey harmlessly adds a redundant secret version.
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       # Claude key (checked in order: -Key, $env:ANTHROPIC_API_KEY, bidbrain-vault\anthropic-api-key.txt)
#       # Gemini key OPTIONAL (-GeminiKey, $env:GEMINI_API_KEY, bidbrain-vault\gemini-api-key.txt)
#       .\clients\client_schneider\dash\enable_report_schneider.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# After this runs once, redeploy the dashboard image normally with deploy_dash_schneider.ps1 - the secret
# mounts + timeout persist across image swaps.

param([string]$Key = "", [string]$GeminiKey = "", [string]$GeminiModel = "gemini-2.5-pro")

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$SERVICE  = "schneider-dash"
$SA       = "schneider-dash-web@bidbrain-analytics.iam.gserviceaccount.com"   # dash runtime SA
$SECRET   = "anthropic-api-key"
$GSECRET  = "gemini-api-key"
$BUCKET   = "bidbrain-analytics-schneider-dash"   # private data bucket - report cache lives in reports/
$TIMEOUT  = "900"   # seconds - room for the web-research + structuring calls

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }

# ---- resolve a key: -arg > env var > bidbrain-vault\<file> --------------------------------------
function Resolve-Key($argVal, $envName, $fileName) {
  if ($argVal) { return $argVal }
  $e = [Environment]::GetEnvironmentVariable($envName); if ($e) { return $e }
  $vault = Join-Path $PSScriptRoot "..\..\..\bidbrain-vault\$fileName"
  if (Test-Path $vault) { return (Get-Content $vault -Raw).Trim() }
  return ""
}

# ---- create/version a secret from a key value, then grant the SA read access --------------------
function Set-Secret($name, $val) {
  $exists = (gcloud secrets describe $name --project $PROJECT --format='value(name)' 2>$null)
  $tmp = [System.IO.Path]::GetTempFileName()
  [System.IO.File]::WriteAllText($tmp, $val)   # exact bytes, NO trailing newline
  try {
    if ($exists) { Write-Host "secret $name exists - adding a new version ..."; gcloud secrets versions add $name --data-file="$tmp" --project $PROJECT }
    else         { Write-Host "creating secret $name ...";                       gcloud secrets create  $name --data-file="$tmp" --replication-policy=automatic --project $PROJECT }
  } finally { [System.IO.File]::Delete($tmp) }
  Must "write secret $name"
  gcloud secrets add-iam-policy-binding $name --member="serviceAccount:$SA" --role="roles/secretmanager.secretAccessor" --project $PROJECT | Out-Null; Must "grant secretAccessor on $name"
}

$Key = Resolve-Key $Key "ANTHROPIC_API_KEY" "anthropic-api-key.txt"
if (-not $Key) { Die "no Claude API key. Pass -Key, set `$env:ANTHROPIC_API_KEY, or create bidbrain-vault\anthropic-api-key.txt" }
Set-Secret $SECRET $Key

$GeminiKey = Resolve-Key $GeminiKey "GEMINI_API_KEY" "gemini-api-key.txt"
$useGemini = [bool]$GeminiKey
if ($useGemini) { Set-Secret $GSECRET $GeminiKey } else { Write-Host "no Gemini key supplied - fallback disabled (Claude only)." }

# ---- grant the runtime SA WRITE on the data bucket so it can cache generated reports ------------
Write-Host "granting storage.objectAdmin on gs://$BUCKET to $SA (report cache) ..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectAdmin" --project $PROJECT | Out-Null; Must "grant bucket write"

# ---- mount the key(s) + set --timeout on the service -------------------------------------------
$secrets = "ANTHROPIC_API_KEY=${SECRET}:latest"
if ($useGemini) { $secrets += ",GEMINI_API_KEY=${GSECRET}:latest" }
$envvars = if ($useGemini) { @("--update-env-vars", "GEMINI_MODEL=$GeminiModel") } else { @() }
Write-Host "mounting secret(s) [$secrets] + --timeout=$TIMEOUT on $SERVICE ..."
gcloud run services update $SERVICE --region $REGION --project $PROJECT --update-secrets $secrets --timeout $TIMEOUT @envvars; Must "update service"

Write-Host "`nDONE. The '/report' endpoint can now reach $([string]::Join(' + ', @('Claude') + @(if($useGemini){'Gemini fallback'}))). " -ForegroundColor Green
Write-Host "Redeploy the dashboard image with deploy_dash_schneider.ps1 to ship report.py + bb_deck.js + the new dashboard.html."
