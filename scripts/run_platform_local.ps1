# run_platform_local.ps1 - run the platform locally with the RAG / Knowledge features switched on.
#
# Memory backend (registry from config.py, nothing written to GCS) + DEV=1 (every production
# mutation - upload, retag, delete, Fathom sync/assign, sync-all, ... - is refused with a loud 503).
# Reads that DO reach GCP, read-only: the knowledge/ prefix listing in the platform bucket, the
# knowledge.chunks table, and one Secret Manager read of gemini-api-key so the pane reports "ready".
#
#   .\scripts\run_platform_local.ps1                 # http://localhost:8085  (super password: local-super)
#   .\scripts\run_platform_local.ps1 -Port 8090
# Then: http://localhost:8085/kb/meetings
#
# /kb (Documents, Meetings, Observability) opens for a superadmin password login (Ian's gate: every
# admin + 100% Digital). KNOWLEDGE_RETRIEVAL=on lets the dashboard staff assistant read /kb;
# CLIENT_CHAT_ENABLED stays OFF here too - no client sees a chatbot until Jerome + Ian decide.
#
# Needs Flask + the parsers in the venv:  .\.venv\Scripts\pip install flask pypdf python-docx python-pptx openpyxl
# gcloud must run BEFORE PYTHONPATH is touched - a stray PYTHONPATH breaks its bundled python.
param(
    [int]$Port = 8085,
    [string]$Retrieval = "on"
)
$root = Split-Path $PSScriptRoot -Parent
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "C:\Projects\BidbrainAI\bidbrain-analytics\.venv\Scripts\python.exe" }

$saved = $env:PYTHONPATH; $env:PYTHONPATH = ""
$env:GEMINI_API_KEY = (& gcloud secrets versions access latest --secret=gemini-api-key --project=bidbrain-analytics --quiet)
$env:PYTHONPATH = $saved

$env:PLATFORM_BACKEND = "memory"
$env:DEV = "1"
$env:SESSION_SECRET = "local-x"
$env:SSO_SECRET = "local-y"
$env:COOKIE_DOMAIN = ""
$env:GOOGLE_CLOUD_PROJECT = "bidbrain-analytics"
$env:SUPER_ADMIN_PW = "local-super"
$env:GCS_BUCKET = "bidbrain-analytics-platform-dash"
$env:KNOWLEDGE_RETRIEVAL = $Retrieval
$env:CLIENT_CHAT_ENABLED = "off"
$env:PORT = "$Port"
$env:PYTHONIOENCODING = "utf-8"

Set-Location (Join-Path $root "bidbrain-platform\dash")
& $py main.py
