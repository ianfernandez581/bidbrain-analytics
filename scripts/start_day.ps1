# start_day.ps1  -  bidbrain-analytics morning preflight
# Verifies BOTH credential systems gcloud uses, plus that the loaders can
# actually read the Windsor key, so nothing surprises you mid-task.
#
#   gcloud CLI creds      -> used by `gcloud secrets ...` (the loaders' key fetch)
#   application-default   -> used by Python client libs (BigQuery)
# These expire independently and your org enforces periodic reauth, so both
# are checked here.
#
# Lives in:  bidbrain-analytics/scripts/
# Run:               .\scripts\start_day.ps1
# Or double-click:   scripts\start_day.cmd

$PROJECT = "bidbrain-analytics"

Set-Location (Split-Path $PSScriptRoot -Parent)

# Prefer the repo's .venv (created by scripts\setup.ps1); fall back to PATH python.
$PY = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

Write-Host ""
Write-Host "=== bidbrain-analytics :: start of day ===" -ForegroundColor Cyan
Write-Host "Working dir: $(Get-Location)" -ForegroundColor DarkGray

# 1. gcloud on PATH?
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "[X] gcloud not found. Open a fresh terminal or reinstall the Cloud SDK." -ForegroundColor Red
    exit 1
}

# 2. gcloud CLI credentials (used by `gcloud secrets` in the loaders).
#    Handle this FIRST so later gcloud calls don't pop a reauth prompt.
Write-Host "[*] Checking gcloud CLI credentials..." -ForegroundColor Yellow
$cliToken = gcloud auth print-access-token 2>$null
if (-not $cliToken) {
    Write-Host "[!] gcloud CLI needs reauth (org session policy). Opening browser..." -ForegroundColor Yellow
    gcloud auth login
} else {
    Write-Host "[OK] gcloud CLI credentials valid." -ForegroundColor Green
}

# 3. Pin the CLI project so `gcloud secrets` looks in the right place.
gcloud config set project $PROJECT 2>$null | Out-Null
Write-Host "[OK] CLI project = $PROJECT" -ForegroundColor Green

# 4. Application-default credentials (used by the Python client libs).
Write-Host "[*] Checking application-default credentials..." -ForegroundColor Yellow
$adcToken = gcloud auth application-default print-access-token 2>$null
if (-not $adcToken) {
    Write-Host "[!] ADC expired - opening browser to log in." -ForegroundColor Yellow
    gcloud auth application-default login | Out-Null
} else {
    Write-Host "[OK] ADC valid." -ForegroundColor Green
}
gcloud auth application-default set-quota-project $PROJECT 2>$null | Out-Null
Write-Host "[OK] ADC quota project = $PROJECT" -ForegroundColor Green

# 5. Eyeball the active account
$account = (gcloud config get-value account 2>$null)
Write-Host "[OK] Active account: $account" -ForegroundColor Green

# 6. Verify the loaders can read the Windsor key (the exact op they do first).
#    Captured to $null so the secret never prints to screen.
Write-Host "[*] Checking Secret Manager (windsor-api-key)..." -ForegroundColor Yellow
$null = gcloud secrets versions access latest --secret windsor-api-key --project $PROJECT 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Windsor key readable - loaders can authenticate." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't read windsor-api-key. If you weren't prompted to reauth," -ForegroundColor Yellow
    Write-Host "    check the secret name / your IAM access to it." -ForegroundColor Yellow
}

# 6b. Verify the GLM launcher can read the shared key (so a launch doesn't fail
#     mid-task). Captured to $null so the secret never prints.
Write-Host "[*] Checking Secret Manager (glm-api-key for GLM launcher)..." -ForegroundColor Yellow
$null = gcloud secrets versions access latest --secret glm-api-key --project $PROJECT 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] glm-api-key readable - GLM launcher ready." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't read glm-api-key (GLM launcher won't work until fixed)." -ForegroundColor Yellow
}

# 7. BigQuery ping via the Python client (same path your loaders use).
Write-Host "[*] Pinging BigQuery (raw_windsor)..." -ForegroundColor Yellow
& $PY -c "from google.cloud import bigquery; bigquery.Client(project='$PROJECT').get_dataset('raw_windsor'); print('ok')" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] BigQuery reachable, raw_windsor found." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't reach raw_windsor via Python (check creds / dataset name)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Ready to go. Common commands:" -ForegroundColor Cyan
Write-Host "  $PY ingest/windsor_data_pull/meta/meta_loader.py"
Write-Host "  $PY ingest/windsor_data_pull/tradedesk/tradedesk_loader.py"
Write-Host "  $PY ingest/windsor_data_pull/meta/create_meta_table.py"
Write-Host ""

