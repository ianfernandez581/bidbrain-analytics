# run.ps1 - run the Foodbank Australia pitch dashboard locally on http://127.0.0.1:8080/
#
#   .\clients\client_foodbank\run.ps1
#
# Uses the repo venv. Password comes from FOODBANK_DASH_PASSWORD; with it unset the app prints its
# dev password to this console on start (never to the page). Regenerates the sample JSON first so
# the dashboard can never serve a payload that disagrees with the generator.
$ErrorActionPreference = "Stop"
$ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$PY = Join-Path $ROOT ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { $PY = "python" }

& $PY (Join-Path $PSScriptRoot "data\generate_sample.py") | Select-Object -Last 1
if ($LASTEXITCODE -ne 0) { Write-Host "!! sample generator failed" -ForegroundColor Red; exit 1 }

if (-not $env:PORT) { $env:PORT = "8080" }
Write-Host "Foodbank dashboard -> http://127.0.0.1:$($env:PORT)/   (Ctrl+C to stop)"
& $PY (Join-Path $PSScriptRoot "dash\main.py")
