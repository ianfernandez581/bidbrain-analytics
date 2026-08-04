# setup_dev.ps1 - one-shot dev setup for The Grid + Greenlight on a fresh machine.
#
#   git fetch; git checkout charles/work        (or whatever branch)
#   .\grid-core\setup_dev.ps1 -Start
#
# What it does, in order:
#   1. npm ci (only when node_modules is missing)
#   2. ensures grid-core\.env holds ANTHROPIC_API_KEY - pulled from Secret
#      Manager (anthropic-api-key:latest, the funded key) when gcloud is
#      logged in; otherwise tells you exactly what to paste
#   3. probes the key with a 1-token call (expected\check_key.js)
#   4. with -Start: runs the Grid at http://localhost:8787 with the
#      Greenlight tab enabled
#
# Safe to re-run anytime; every step skips itself when already done.

param([switch]$Start)

$GRID = $PSScriptRoot
$PROJECT = "bidbrain-analytics"

function Die($m) { Write-Host "!! $m" -ForegroundColor Red; exit 1 }

# ---- 1. node deps -------------------------------------------------------
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "node not found - install Node 20+ first (https://nodejs.org)" }
Write-Host "node $(node --version)"
if (-not (Test-Path (Join-Path $GRID "node_modules"))) {
  Write-Host "Installing dependencies (npm ci) ..."
  Push-Location $GRID
  npm ci
  $ok = ($LASTEXITCODE -eq 0)
  Pop-Location
  if (-not $ok) { Die "npm ci failed" }
} else {
  Write-Host "node_modules present - skipping npm ci"
}

# ---- 2. the API key -----------------------------------------------------
$envPath = Join-Path $GRID ".env"
$hasKey = (Test-Path $envPath) -and ((Get-Content $envPath -Raw) -match 'ANTHROPIC_API_KEY\s*=\s*\S')
if ($hasKey) {
  Write-Host "grid-core\.env already carries ANTHROPIC_API_KEY - keeping it"
} else {
  Write-Host "No key in grid-core\.env - trying Secret Manager (anthropic-api-key:latest) ..."
  $key = $null
  if (Get-Command gcloud -ErrorAction SilentlyContinue) {
    $key = (gcloud secrets versions access latest --secret=anthropic-api-key --project=$PROJECT 2>$null)
    if ($LASTEXITCODE -ne 0) { $key = $null }
  }
  if ($key) {
    [IO.File]::WriteAllText($envPath, "ANTHROPIC_API_KEY=$($key.Trim())`n")
    Write-Host "Pulled the funded key from Secret Manager into grid-core\.env (gitignored)"
  } else {
    Write-Host "!! Could not reach Secret Manager (gcloud missing or not logged in)." -ForegroundColor Yellow
    Write-Host "   Either run: gcloud auth login   and re-run this script," -ForegroundColor Yellow
    Write-Host "   or create grid-core\.env yourself with one line: ANTHROPIC_API_KEY=sk-ant-..." -ForegroundColor Yellow
    Die "no API key available - Greenlight extraction cannot run without it"
  }
}

# ---- 3. probe the key (1-token call, never prints the key) --------------
node (Join-Path $GRID "expected\check_key.js")
if ($LASTEXITCODE -ne 0) { Die "the key in grid-core\.env is not usable - see the probe output above" }

# ---- 4. run -------------------------------------------------------------
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
if ($Start) {
  Write-Host "Starting The Grid with the Greenlight tab at http://localhost:8787/the-grid.html ..."
  $env:GREENLIGHT_ENABLED = "true"
  Push-Location $GRID
  node server.js
  Pop-Location
} else {
  Write-Host "Run the Grid:        `$env:GREENLIGHT_ENABLED='true'; node grid-core\server.js"
  Write-Host "Standalone harness:  node grid-core\expected\server.js   (http://localhost:8791)"
}
