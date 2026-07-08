# enable_report_mongodb.ps1 - ONE-TIME standup for the "Download report" feature (dash/report.py).
# Provisions the Claude key (required) and the optional Gemini fallback key, grants the dashboard's
# runtime service account secret-read + bucket-write (for the report cache), mounts the keys on the
# mongodb-dash service, and bumps the Cloud Run request timeout so the two-stage Claude/Gemini call
# (web research + structuring) can finish. Idempotent: safe to re-run (e.g. to rotate a key).
#
#   HOW TO RUN (from anywhere - paths resolve from the script's own folder):
#       # Claude key (checked in order: -Key, $env:ANTHROPIC_API_KEY, bidbrain-vault\anthropic-api-key.txt)
#       # Gemini key is OPTIONAL (enables fallback when Claude rate-limits):
#       #   -GeminiKey, $env:GEMINI_API_KEY, bidbrain-vault\gemini-api-key.txt
#       .\client_mongodb\dash\enable_report_mongodb.ps1 -Key "sk-ant-..." -GeminiKey "AQ...."
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# After this runs once, redeploy the dashboard image normally with deploy_dash_mongodb.ps1 - the
# secret mounts + timeout persist across image swaps.

param([string]$Key = "", [string]$GeminiKey = "", [string]$GeminiModel = "gemini-2.5-pro")

$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$SERVICE  = "mongodb-dash"
$SA       = "mongodb-dash-web@bidbrain-analytics.iam.gserviceaccount.com"   # dash runtime SA
$SECRET   = "anthropic-api-key"
$GSECRET  = "gemini-api-key"
$BUCKET   = "bidbrain-analytics-mongodb-dash"   # private data bucket - report cache lives in reports/
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
# Gemini on VERTEX AI is the DEFAULT generator (project-billed via $SA below; no key). The Claude
# key is OPTIONAL now - only mounted if supplied, in which case Claude becomes a fallback.
$useClaude = [bool]$Key
if ($useClaude) { Set-Secret $SECRET $Key } else { Write-Host "no Claude key supplied - decks run on Vertex Gemini only (the default)." }

$GeminiKey = Resolve-Key $GeminiKey "GEMINI_API_KEY" "gemini-api-key.txt"
$useGemini = [bool]$GeminiKey
if ($useGemini) { Set-Secret $GSECRET $GeminiKey } else { Write-Host "no Gemini key supplied - fallback disabled (Claude only)." }

# ---- grant the runtime SA WRITE on the data bucket so it can cache generated reports ------------
Write-Host "granting storage.objectAdmin on gs://$BUCKET to $SA (report cache) ..."
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" --role="roles/storage.objectAdmin" --project $PROJECT | Out-Null; Must "grant bucket write"

# ---- grant the runtime SA Vertex AI access (report.py DEFAULT generator = Gemini on Vertex) ----
Write-Host "granting roles/aiplatform.user to $SA (Vertex AI Gemini) ..."
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:$SA" --role="roles/aiplatform.user" --condition=None --quiet | Out-Null; Must "grant aiplatform.user"

# ---- mount the key(s) + set --timeout on the service -------------------------------------------
$secretParts = @()
if ($useClaude) { $secretParts += "ANTHROPIC_API_KEY=${SECRET}:latest" }
if ($useGemini) { $secretParts += "GEMINI_API_KEY=${GSECRET}:latest" }
# GEMINI_MODEL picks the Vertex model (gemini-2.5-flash serves in au; gemini-2.5-pro auto-uses
# the global endpoint via report.py's region fallback). Always set it.
$upd = @("--update-env-vars", "GEMINI_MODEL=$GeminiModel", "--timeout", $TIMEOUT)
if ($secretParts.Count -gt 0) { $upd += @("--update-secrets", ($secretParts -join ",")) }
Write-Host "updating $SERVICE (GEMINI_MODEL=$GeminiModel, timeout=$TIMEOUT) ..."
gcloud run services update $SERVICE --region $REGION --project $PROJECT @upd; Must "update service"

Write-Host "`nDONE. The 'Download report' endpoint can now reach $([string]::Join(' + ', @('Claude') + @(if($useGemini){'Gemini fallback'}))). " -ForegroundColor Green
Write-Host "Redeploy the dashboard image with deploy_dash_mongodb.ps1 to ship report.py + the new dashboard.html."
