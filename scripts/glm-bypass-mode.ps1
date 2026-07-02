<#
  glm-bypass-mode.ps1  -  launch Claude Code on Z.ai GLM (shared org key)
  ---------------------------------------------------------------
  Claude Code normally talks to the Anthropic API. This launcher re-points it at
  Z.ai's Anthropic-compatible endpoint and the GLM model family, using ONE org
  key shared from Secret Manager (glm-api-key) so every dev runs the SAME setup
  without a per-machine key.

  It sets these ONLY for the Claude process and restores/clears them afterwards,
  so the token never lingers in your shell after Claude exits:
    ANTHROPIC_BASE_URL                  https://api.z.ai/api/anthropic
    ANTHROPIC_AUTH_TOKEN                (from Secret Manager; never printed)
    ANTHROPIC_DEFAULT_OPUS_MODEL        glm-5.2
    ANTHROPIC_DEFAULT_SONNET_MODEL      glm-5.2
    ANTHROPIC_DEFAULT_HAIKU_MODEL       glm-4.7

  Run:
    .\scripts\glm-bypass-mode.ps1              # launch in THIS terminal
    .\scripts\glm-bypass-mode.ps1 -NewWindow   # launch in a fresh window
    .\scripts\glm-bypass-mode.cmd              # double-click = fresh window
    .\scripts\glm-bypass-mode.ps1 --resume <id># any extra args pass straight to claude

  Prereqs: `claude` on PATH + gcloud logged in with access to glm-api-key.
  scripts\setup.ps1 verifies both; scripts\start_day.ps1 checks the secret daily.

  Lives in:  bidbrain-analytics/scripts/
#>

[CmdletBinding()]
param(
    [switch]$NewWindow,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ClaudeArgs
)

$ErrorActionPreference = "Stop"
$PROJECT = "bidbrain-analytics"
$SECRET  = "glm-api-key"

# Run from repo root regardless of cwd.
if ($PSScriptRoot) { Set-Location (Split-Path $PSScriptRoot -Parent) }

# --- 1. claude CLI present? ---------------------------------------------------
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    Write-Host "[X] 'claude' not found on PATH." -ForegroundColor Red
    Write-Host "    Install Claude Code:  npm install -g @anthropic-ai/claude-code" -ForegroundColor Yellow
    Write-Host "    (or the native installer from https://claude.ai/code)" -ForegroundColor Yellow
    exit 1
}

# --- 2. -NewWindow: spawn a fresh terminal that re-runs THIS script inline -----
# Re-fetching the secret inside the child keeps the token out of any command-line
# arg or window title. The child is launched WITHOUT -NewWindow, so no recursion.
if ($NewWindow) {
    $psExe = (Get-Process -Id $PID).Path      # powershell.exe / pwsh.exe
    $self  = $MyInvocation.MyCommand.Path
    Start-Process -FilePath $psExe -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $self)
    return
}

# --- 3. fetch the key from Secret Manager (never print it) --------------------
Write-Host "[*] Reading $SECRET from Secret Manager..." -ForegroundColor Yellow
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$tok = $null
try {
    $tok = (gcloud secrets versions access latest --secret $SECRET --project $PROJECT 2>$null)
} catch {}
$ErrorActionPreference = $prevEAP
if (-not $tok) {
    Write-Host "[X] Could not read $SECRET." -ForegroundColor Red
    Write-Host "    Check 'gcloud auth login' and that your identity can access the secret." -ForegroundColor Yellow
    Write-Host "    If needed:" -ForegroundColor Yellow
    Write-Host "      gcloud secrets add-iam-policy-binding $SECRET --member=<you> --role=roles/secretmanager.secretAccessor" -ForegroundColor Yellow
    exit 1
}

# --- 4. set env for the Claude process (snapshot prior values to restore) ------
$vars = [ordered]@{
    ANTHROPIC_BASE_URL             = "https://api.z.ai/api/anthropic"
    ANTHROPIC_AUTH_TOKEN           = $tok
    ANTHROPIC_DEFAULT_OPUS_MODEL   = "glm-5.2"
    ANTHROPIC_DEFAULT_SONNET_MODEL = "glm-5.2"
    ANTHROPIC_DEFAULT_HAIKU_MODEL  = "glm-4.7"
}
$prior = @{}
foreach ($k in $vars.Keys) { $prior[$k] = [Environment]::GetEnvironmentVariable($k, "Process") }
foreach ($k in $vars.Keys) { [Environment]::SetEnvironmentVariable($k, $vars[$k], "Process") }

Write-Host "[OK] Launching Claude Code on GLM 5.2 (Z.ai)..." -ForegroundColor Green
Write-Host "     endpoint https://api.z.ai/api/anthropic  |  opus/sonnet=glm-5.2  haiku=glm-4.7" -ForegroundColor DarkGray
try {
    & claude @ClaudeArgs
}
finally {
    # Restore prior env so the token does not outlive this script.
    foreach ($k in $vars.Keys) {
        [Environment]::SetEnvironmentVariable($k, $prior[$k], "Process")
    }
}
