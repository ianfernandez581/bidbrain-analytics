<#
  setup.ps1  -  bidbrain-analytics one-shot machine setup
  -------------------------------------------------------
  Run ONCE on any fresh Windows machine after cloning the repo:

      git clone <repo>
      cd bidbrain-analytics
      .\scripts\setup.ps1          (or double-click scripts\setup.cmd)

  Everything below is IDEMPOTENT - safe to run again any time.
  Steps:
    1. Install Python 3.12 if missing (winget)
    2. Install Google Cloud SDK if missing (winget)
    3. Verify the committed requirements files are present (root + export job)
    4. Create an isolated .venv and install dependencies into it
    5. Log in to gcloud (CLI creds + application-default) - the one manual step
    6. Verify it can read the Windsor secret and reach BigQuery

  NOTE: the committed source is portable as-is (loaders read secrets via ADC,
  start_day.ps1 auto-resolves Python). This script never edits tracked files.

  After this, run a loader with the venv's python:
      .\.venv\Scripts\python.exe ingest\windsor_data_pull\meta\meta_loader.py
#>

$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"

# --- Locate repo root ---------------------------------------------------------
if ($PSScriptRoot) { Set-Location (Split-Path $PSScriptRoot -Parent) }
$REPO = (Get-Location).Path
if (-not (Test-Path (Join-Path $REPO "ingest/windsor_data_pull"))) {
    Write-Host "[X] Run this from the bidbrain-analytics repo root (ingest/windsor_data_pull not found here)." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== bidbrain-analytics :: one-shot setup ===" -ForegroundColor Cyan
Write-Host "Repo: $REPO" -ForegroundColor DarkGray

# --- Helper: refresh PATH in the current session (so freshly-installed CLIs appear) ---
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = ($machine, $user | Where-Object { $_ }) -join ";"
}

# --- Helper: run a probe command whose failure is EXPECTED and handled here. ----
# With $ErrorActionPreference = "Stop", redirecting a native command's stderr
# (2>$null) turns its error output into a terminating NativeCommandError, which
# would abort the whole script. We drop to "Continue" for the probe and report
# success purely from the exit code, so a failed check just returns $false.
function Test-Probe {
    param([scriptblock]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Command 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

# --- 1. Python ----------------------------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "[*] Python not found - installing Python 3.12 via winget..." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "[X] winget unavailable. Install Python 3.12 from python.org, then re-run." -ForegroundColor Red
        exit 1
    }
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    Update-SessionPath
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "[!] Python installed. Close this terminal, open a NEW one, and re-run setup." -ForegroundColor Yellow
        exit 0
    }
}
Write-Host "[OK] Python: $((Get-Command python).Source)" -ForegroundColor Green

# --- 2. Google Cloud SDK ------------------------------------------------------
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "[*] gcloud not found - installing Google Cloud SDK via winget..." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "[X] winget unavailable. Install the Cloud SDK manually, then re-run." -ForegroundColor Red
        exit 1
    }
    winget install -e --id Google.CloudSDK --accept-source-agreements --accept-package-agreements
    Update-SessionPath
    if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
        Write-Host "[!] gcloud installed. Close this terminal, open a NEW one, and re-run setup." -ForegroundColor Yellow
        exit 0
    }
}
Write-Host "[OK] gcloud: $((Get-Command gcloud).Source)" -ForegroundColor Green

# --- 3. requirements files (must be committed in the repo) --------------------
# The local .venv is a convenience superset for running everything locally:
#   - requirements.txt                    -> Windsor loaders + BigQuery setup scripts
#   - clients/client_mongodb/job/requirements.txt -> the MongoDB export job (main.py:
#                                            BigQuery + Storage clients only)
# Both pin google-cloud-bigquery/storage to the SAME versions, so they coexist
# in one venv (verified with `pip check`). The dash web app is deliberately
# EXCLUDED: it pins google-cloud-storage==2.18.2, which conflicts with the
# 3.10.1 used here. Each Cloud Run unit still builds its own container from its
# own requirements.txt, so this dev-only superset never affects image builds.
$reqFiles = @(
    (Join-Path $REPO "requirements.txt"),
    (Join-Path $REPO "clients\client_mongodb\job\requirements.txt")
)
foreach ($r in $reqFiles) {
    if (-not (Test-Path $r)) {
        Write-Host "[X] Missing committed requirements file:" -ForegroundColor Red
        Write-Host "    $r" -ForegroundColor Red
        Write-Host "    It is version-controlled -- restore it with 'git checkout -- <path>' and re-run." -ForegroundColor Red
        exit 1
    }
}
Write-Host "[OK] requirements files present (root + export job)" -ForegroundColor Green

# --- 4. venv + dependencies ---------------------------------------------------
$venvPy = Join-Path $REPO ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[*] Creating .venv..." -ForegroundColor Yellow
    python -m venv .venv
}
Write-Host "[*] Installing dependencies into .venv..." -ForegroundColor Yellow
& $venvPy -m pip install --upgrade pip | Out-Null
foreach ($r in $reqFiles) {
    Write-Host "    pip install -r $r" -ForegroundColor DarkGray
    & $venvPy -m pip install -r $r
}
Write-Host "[OK] Dependencies installed into .venv (loaders + export job)" -ForegroundColor Green

# --- 5. Authenticate (the one manual step - a browser will open) --------------
Write-Host "[*] Checking gcloud CLI credentials..." -ForegroundColor Yellow
if (-not (Test-Probe { gcloud auth print-access-token })) {
    Write-Host "    Opening browser for gcloud login..." -ForegroundColor Yellow
    gcloud auth login
}
Test-Probe { gcloud config set project $PROJECT } | Out-Null

Write-Host "[*] Checking application-default credentials..." -ForegroundColor Yellow
if (-not (Test-Probe { gcloud auth application-default print-access-token })) {
    Write-Host "    Opening browser for application-default login..." -ForegroundColor Yellow
    gcloud auth application-default login
}
Test-Probe { gcloud auth application-default set-quota-project $PROJECT } | Out-Null
$account = (& gcloud config get-value account 2>$null)
Write-Host "[OK] Authenticated as $account" -ForegroundColor Green

# --- 6. Verify secret + BigQuery ---------------------------------------------
Write-Host "[*] Verifying Windsor secret access..." -ForegroundColor Yellow
if (Test-Probe { gcloud secrets versions access latest --secret windsor-api-key --project $PROJECT }) {
    Write-Host "[OK] Windsor secret readable" -ForegroundColor Green
} else {
    Write-Host "[!] Could not read windsor-api-key (check IAM / secret name)" -ForegroundColor Yellow
}

Write-Host "[*] Verifying BigQuery (raw_windsor)..." -ForegroundColor Yellow
if (Test-Probe { & $venvPy -c "from google.cloud import bigquery; bigquery.Client(project='$PROJECT', location='australia-southeast1').get_dataset('raw_windsor'); print('ok')" }) {
    Write-Host "[OK] BigQuery reachable, raw_windsor found" -ForegroundColor Green
} else {
    Write-Host "[!] Could not reach raw_windsor via Python (check creds / dataset)" -ForegroundColor Yellow
}

# --- Done ---------------------------------------------------------------------
Write-Host ""
Write-Host "Setup complete. Run a loader:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe ingest\windsor_data_pull\meta\meta_loader.py"
Write-Host "  .\.venv\Scripts\python.exe ingest\windsor_data_pull\tradedesk\tradedesk_loader.py"
Write-Host ""
Write-Host "Run the MongoDB export job locally (sets env + pulls the Snowflake key):" -ForegroundColor DarkGray
Write-Host "  .\scripts\run-export-job.ps1 -DryRun   (verify env, no prod write)" -ForegroundColor DarkGray
Write-Host "  .\scripts\run-export-job.ps1           (runs it; prompts first)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "Each new session, run the preflight first:  .\scripts\start_day.ps1" -ForegroundColor DarkGray
Write-Host ""