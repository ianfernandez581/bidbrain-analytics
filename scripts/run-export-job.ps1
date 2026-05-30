<#
  run-export-job.ps1  -  run the MongoDB export job locally
  ----------------------------------------------------------
  The job (client_mongodb/job/main.py) normally runs as a Cloud Run JOB, which
  injects its config via --set-env-vars / --set-secrets. This script reproduces
  that environment locally so you can run it from a fresh clone:

      .\scripts\run-export-job.ps1            # prompts before writing to prod
      .\scripts\run-export-job.ps1 -DryRun    # set env + verify secret, DON'T run
      .\scripts\run-export-job.ps1 -Force     # skip the confirmation prompt

  WARNING: a real run is NOT a no-op. It WRITE_TRUNCATEs the BigQuery tables
  client_mongodb.src_tradedesk / src_salesforce and overwrites the live
  dashboard data at gs://<bucket>/mongodb.json.

  The non-secret values below MIRROR client_mongodb/job/cloudbuild.yaml
  (--set-env-vars). The SNOWFLAKE_KEY is pulled from Secret Manager, exactly as
  Cloud Run mounts it (--set-secrets=SNOWFLAKE_KEY=snowflake-bq-key:latest).
  >> Keep these in sync if the deploy config changes. <<
#>
param(
    [switch]$Force,
    [switch]$DryRun
)

$PROJECT = "bidbrain-analytics"
$SECRET  = "snowflake-bq-key"     # Secret Manager secret holding the Snowflake PEM key

# --- Locate repo root + venv python (same pattern as start_day.ps1) -----------
Set-Location (Split-Path $PSScriptRoot -Parent)
$JOB = ".\client_mongodb\job\main.py"
$PY  = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

Write-Host ""
Write-Host "=== bidbrain-analytics :: MongoDB export job ===" -ForegroundColor Cyan
Write-Host "Working dir: $(Get-Location)" -ForegroundColor DarkGray

if (-not (Test-Path $JOB)) {
    Write-Host "[X] $JOB not found - run this from a full clone of the repo." -ForegroundColor Red
    exit 1
}

# --- 1. Non-secret config (mirrors cloudbuild.yaml --set-env-vars) ------------
$env:GCP_PROJECT  = $PROJECT
$env:BQ_DATASET   = "client_mongodb"
$env:GCS_BUCKET   = "bidbrain-analytics-mongodb-dash"
$env:SF_ACCOUNT   = "ZGKGHOH-ISA98947"
$env:SF_USER      = "BQ_SYNC_USER"
$env:SF_WAREHOUSE = "APAC_IN_WH"
Write-Host "[OK] Env set: project=$($env:GCP_PROJECT) dataset=$($env:BQ_DATASET) bucket=$($env:GCS_BUCKET)" -ForegroundColor Green
Write-Host "            snowflake account=$($env:SF_ACCOUNT) user=$($env:SF_USER) warehouse=$($env:SF_WAREHOUSE)" -ForegroundColor DarkGray

# --- 2. Snowflake key from Secret Manager (captured so it never prints) -------
# Out-String preserves the PEM's newlines; a bare assignment would flatten the
# multi-line key into spaces and load_pem_private_key() would reject it.
Write-Host "[*] Fetching Snowflake key from Secret Manager ($SECRET)..." -ForegroundColor Yellow
$key = (gcloud secrets versions access latest --secret $SECRET --project $PROJECT 2>$null | Out-String)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($key)) {
    Write-Host "[X] Could not read secret '$SECRET'." -ForegroundColor Red
    Write-Host "    If you weren't prompted to reauth, you likely lack Secret Manager" -ForegroundColor Red
    Write-Host "    accessor on it (roles/secretmanager.secretAccessor) - an IAM grant," -ForegroundColor Red
    Write-Host "    not a code problem. Run .\scripts\start_day.ps1 to refresh creds first." -ForegroundColor Red
    exit 1
}
$env:SNOWFLAKE_KEY = $key
Write-Host "[OK] Snowflake key loaded into `$env:SNOWFLAKE_KEY (not printed)." -ForegroundColor Green

# --- 3. Dry run stops here: env is proven, nothing was written ----------------
if ($DryRun) {
    Write-Host ""
    Write-Host "[OK] Dry run: environment is ready and the secret is readable." -ForegroundColor Green
    Write-Host "     Re-run without -DryRun to execute the job (writes to prod)." -ForegroundColor DarkGray
    exit 0
}

# --- 4. Confirm (it overwrites production) ------------------------------------
if (-not $Force) {
    Write-Host ""
    Write-Host "This OVERWRITES production data:" -ForegroundColor Yellow
    Write-Host "  - BigQuery $($env:BQ_DATASET).src_tradedesk / src_salesforce  (WRITE_TRUNCATE)" -ForegroundColor Yellow
    Write-Host "  - gs://$($env:GCS_BUCKET)/mongodb.json  (the live dashboard data)" -ForegroundColor Yellow
    $ans = Read-Host "Type 'yes' to run the export job"
    if ($ans -ne 'yes') { Write-Host "Aborted - nothing was written." -ForegroundColor DarkGray; exit 0 }
}

# --- 5. Run -------------------------------------------------------------------
Write-Host "[*] Running export job..." -ForegroundColor Yellow
& $PY $JOB
exit $LASTEXITCODE
