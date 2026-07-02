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

# --- Helper: find a REAL python.exe, ignoring the Microsoft Store "App execution
# alias" stub. That stub (a 0-byte shim under ...\WindowsApps\python.exe) lands on
# PATH by default, satisfies `Get-Command python`, but only opens the Store and
# makes `python -m venv` print "Python was not found" and do nothing. We skip any
# python whose path is under WindowsApps, then fall back to the winget/python.org
# install location. Returns a usable exe path, or $null if none is installed.
function Get-RealPython {
    $onPath = Get-Command python -All -ErrorAction SilentlyContinue |
              Where-Object { $_.Source -and $_.Source -notmatch 'WindowsApps' } |
              Select-Object -First 1 -ExpandProperty Source
    if ($onPath) { return $onPath }
    return (Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                          "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName)
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
$realPython = Get-RealPython
if (-not $realPython) {
    Write-Host "[*] Real Python not found (only the Microsoft Store stub, if any) - installing Python 3.12 via winget..." -ForegroundColor Yellow
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "[X] winget unavailable. Install Python 3.12 from python.org, then re-run." -ForegroundColor Red
        exit 1
    }
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --scope user
    Update-SessionPath
    $realPython = Get-RealPython
    if (-not $realPython) {
        Write-Host "[!] Python installed. Close this terminal, open a NEW one, and re-run setup." -ForegroundColor Yellow
        exit 0
    }
}
Write-Host "[OK] Python: $realPython" -ForegroundColor Green

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
    # Use the resolved real python (NOT bare `python`, which may be the Store stub).
    & $realPython -m venv .venv
    if (-not (Test-Path $venvPy)) {
        Write-Host "[X] .venv was not created -- '$realPython -m venv' produced no $venvPy." -ForegroundColor Red
        Write-Host "    Most likely 'python' resolved to the Microsoft Store stub. Disable it via" -ForegroundColor Red
        Write-Host "    Settings > Apps > Advanced app settings > App execution aliases (turn OFF" -ForegroundColor Red
        Write-Host "    python.exe and python3.exe), then re-run this script." -ForegroundColor Red
        exit 1
    }
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

# --- 7. Claude Code (GLM bypass) prerequisites --------------------------------
# Optional dev convenience (NOT required by the data pipeline): the GLM launcher
# (scripts\glm-bypass-mode.ps1) needs (a) the `claude` CLI and (b) read access to
# the shared glm-api-key secret. Both checks are WARN-ONLY - they never block setup,
# and setup NEVER auto-installs claude (that's a dev decision).
Write-Host "[*] Checking Claude Code CLI..." -ForegroundColor Yellow
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Write-Host "[!] 'claude' not found - the GLM launcher (glm-bypass-mode.ps1) needs it." -ForegroundColor Yellow
    Write-Host "    Install it yourself (setup does NOT auto-install):" -ForegroundColor Yellow
    Write-Host "      npm install -g @anthropic-ai/claude-code" -ForegroundColor Yellow
    Write-Host "    or the native installer from https://claude.ai/code" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Claude Code CLI present" -ForegroundColor Green
}

Write-Host "[*] Checking Secret Manager (glm-api-key for GLM launcher)..." -ForegroundColor Yellow
if (Test-Probe { gcloud secrets versions access latest --secret glm-api-key --project $PROJECT }) {
    Write-Host "[OK] glm-api-key readable - GLM launcher will work." -ForegroundColor Green
} else {
    Write-Host "[!] Could not read glm-api-key - the GLM launcher won't work until you can." -ForegroundColor Yellow
    Write-Host "    It may not exist yet, or your identity lacks access. If the latter:" -ForegroundColor Yellow
    Write-Host "      gcloud secrets add-iam-policy-binding glm-api-key --member=<you> --role=roles/secretmanager.secretAccessor" -ForegroundColor Yellow
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