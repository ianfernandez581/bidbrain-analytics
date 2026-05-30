# start_day.ps1  -  bidbrain-analytics morning preflight
# Refreshes Google auth (the thing that expires overnight), sets the quota
# project, and pings BigQuery so you know you're good before running anything.
#
# Lives in:  bidbrain-analytics/scripts/
# Run:               .\scripts\start_day.ps1   (from the project folder)
# Or double-click:   scripts\start_day.cmd     (no execution-policy fuss)

$PROJECT = "bidbrain-analytics"

# This script lives in <repo>/scripts/. Hop up to the repo root so the python
# commands below resolve no matter where you launched it from.
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host ""
Write-Host "=== bidbrain-analytics :: start of day ===" -ForegroundColor Cyan
Write-Host "Working dir: $(Get-Location)" -ForegroundColor DarkGray

# 1. gcloud on PATH?
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "[X] gcloud not found. Open a fresh terminal or reinstall the Cloud SDK." -ForegroundColor Red
    exit 1
}

# 2. Are application-default credentials still valid?
#    print-access-token succeeds only if ADC is good; otherwise we re-auth.
Write-Host "[*] Checking Google credentials..." -ForegroundColor Yellow
$token = gcloud auth application-default print-access-token 2>$null
if (-not $token) {
    Write-Host "[!] Credentials expired - opening browser to log in." -ForegroundColor Yellow
    gcloud auth application-default login | Out-Null
} else {
    Write-Host "[OK] Credentials valid." -ForegroundColor Green
}

# 3. Quota project (silences the 'no quota project' warning + avoids quota errors)
gcloud auth application-default set-quota-project $PROJECT 2>$null | Out-Null
Write-Host "[OK] Quota project = $PROJECT" -ForegroundColor Green

# 4. Eyeball the active account
$account = (gcloud config get-value account 2>$null)
Write-Host "[OK] Active account: $account" -ForegroundColor Green

# 5. Soft BigQuery ping (won't block the day if it hiccups)
Write-Host "[*] Pinging BigQuery (raw_windsor)..." -ForegroundColor Yellow
bq ls --project_id=$PROJECT raw_windsor 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] BigQuery reachable." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't list raw_windsor (auth ok; check dataset / run 'bq init')." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Ready to go. Common commands:" -ForegroundColor Cyan
Write-Host "  python infra/create_meta_table.py"
Write-Host "  python windsor_data_pull/facebook_ads_loader.py"
Write-Host "  python windsor_data_pull/tradedesk_loader.py"
Write-Host ""