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
    3. Create requirements.txt if missing
    4. Create an isolated .venv and install dependencies into it
    5. De-hardcode the machine-specific paths in the loaders + start_day.ps1
       (only touches files that still contain the old C:\Users\ianfe paths;
        review the changes afterwards with `git diff`)
    6. Log in to gcloud (CLI creds + application-default) - the one manual step
    7. Verify it can read the Windsor secret and reach BigQuery

  After this, run a loader with the venv's python:
      .\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py
#>

$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"

# --- Locate repo root ---------------------------------------------------------
if ($PSScriptRoot) { Set-Location (Split-Path $PSScriptRoot -Parent) }
$REPO = (Get-Location).Path
if (-not (Test-Path (Join-Path $REPO "windsor_data_pull"))) {
    Write-Host "[X] Run this from the bidbrain-analytics repo root (windsor_data_pull not found here)." -ForegroundColor Red
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

# --- 3. requirements.txt (create if missing) ----------------------------------
$reqPath = Join-Path $REPO "requirements.txt"
if (-not (Test-Path $reqPath)) {
    @(
        "google-cloud-bigquery",
        "google-cloud-storage",
        "google-cloud-secret-manager",
        "requests"
    ) | Set-Content -Path $reqPath -Encoding ascii
    Write-Host "[OK] Created requirements.txt (commit this to the repo)" -ForegroundColor Green
} else {
    Write-Host "[OK] requirements.txt present" -ForegroundColor DarkGray
}

# --- 4. venv + dependencies ---------------------------------------------------
$venvPy = Join-Path $REPO ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "[*] Creating .venv..." -ForegroundColor Yellow
    python -m venv .venv
}
Write-Host "[*] Installing dependencies into .venv..." -ForegroundColor Yellow
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r requirements.txt
Write-Host "[OK] Dependencies installed into .venv" -ForegroundColor Green

# --- 5. De-hardcode machine-specific paths (idempotent) -----------------------
# 5a. The two loaders: replace the hardcoded gcloud.cmd path with a PATH lookup.
foreach ($loader in @("windsor_data_pull\meta\meta_loader.py",
                      "windsor_data_pull\tradedesk\tradedesk_loader.py")) {
    if (-not (Test-Path $loader)) { continue }
    $c = Get-Content $loader -Raw
    if ($c -match 'GCLOUD\s*=\s*r?"[^"]*gcloud[^"]*"') {
        $c = $c -replace 'GCLOUD\s*=\s*r?"[^"]*gcloud[^"]*"',
                         'GCLOUD = shutil.which("gcloud") or shutil.which("gcloud.cmd")'
        if ($c -notmatch '(?m)^\s*import\s+shutil\b') {
            if ($c -match '(?m)^import\s+sys\s*$') {
                $c = $c -replace '(?m)^(import\s+sys\s*)$', "`$1`nimport shutil"
            } else {
                $c = "import shutil`n" + $c
            }
        }
        [System.IO.File]::WriteAllText((Resolve-Path $loader), $c)
        Write-Host "[OK] De-hardcoded gcloud path in $loader" -ForegroundColor Green
    } else {
        Write-Host "[OK] $loader already clean" -ForegroundColor DarkGray
    }
}

# 5b. start_day.ps1: point $PY at the venv instead of the hardcoded Python314 path.
$sd = "scripts\start_day.ps1"
if (Test-Path $sd) {
    $c = Get-Content $sd -Raw
    if ($c -match '\$PY\s*=\s*"[^"]*Python314[^"]*"') {
        $repl = '$$PY = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }'
        $c = $c -replace '\$PY\s*=\s*"[^"]*Python314[^"]*"', $repl
        [System.IO.File]::WriteAllText((Resolve-Path $sd), $c)
        Write-Host "[OK] start_day.ps1 now uses the venv python" -ForegroundColor Green
    } else {
        Write-Host "[OK] start_day.ps1 already clean" -ForegroundColor DarkGray
    }
}

# --- 6. Authenticate (the one manual step - a browser will open) --------------
Write-Host "[*] Checking gcloud CLI credentials..." -ForegroundColor Yellow
if (-not (gcloud auth print-access-token 2>$null)) {
    Write-Host "    Opening browser for gcloud login..." -ForegroundColor Yellow
    gcloud auth login
}
gcloud config set project $PROJECT 2>$null | Out-Null

Write-Host "[*] Checking application-default credentials..." -ForegroundColor Yellow
if (-not (gcloud auth application-default print-access-token 2>$null)) {
    Write-Host "    Opening browser for application-default login..." -ForegroundColor Yellow
    gcloud auth application-default login
}
gcloud auth application-default set-quota-project $PROJECT 2>$null | Out-Null
Write-Host "[OK] Authenticated as $(gcloud config get-value account 2>$null)" -ForegroundColor Green

# --- 7. Verify secret + BigQuery ---------------------------------------------
Write-Host "[*] Verifying Windsor secret access..." -ForegroundColor Yellow
$null = gcloud secrets versions access latest --secret windsor-api-key --project $PROJECT 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] Windsor secret readable" -ForegroundColor Green }
else { Write-Host "[!] Could not read windsor-api-key (check IAM / secret name)" -ForegroundColor Yellow }

Write-Host "[*] Verifying BigQuery (raw_windsor)..." -ForegroundColor Yellow
& $venvPy -c "from google.cloud import bigquery; bigquery.Client(project='$PROJECT', location='australia-southeast1').get_dataset('raw_windsor'); print('ok')" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "[OK] BigQuery reachable, raw_windsor found" -ForegroundColor Green }
else { Write-Host "[!] Could not reach raw_windsor via Python (check creds / dataset)" -ForegroundColor Yellow }

# --- Done ---------------------------------------------------------------------
Write-Host ""
Write-Host "Setup complete. Run a loader:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py"
Write-Host "  .\.venv\Scripts\python.exe windsor_data_pull\tradedesk\tradedesk_loader.py"
Write-Host ""
Write-Host "One-time housekeeping: add '.venv/' to .gitignore, then commit" -ForegroundColor DarkGray
Write-Host "requirements.txt and the de-hardcoded files so the next clone is clean." -ForegroundColor DarkGray
Write-Host ""