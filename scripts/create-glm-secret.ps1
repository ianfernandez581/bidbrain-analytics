<#
  create-glm-secret.ps1  -  one-time bootstrap of the shared glm-api-key secret
  ---------------------------------------------------------------
  Prompts (MASKED) for the Z.ai / GLM API key and stores it in Secret Manager as
  `glm-api-key`, so every dev's glm-bypass-mode.ps1 launcher can pull it at run
  time. Run ONCE (by whoever has the key):

      .\scripts\create-glm-secret.ps1

  Idempotent: creates the secret if absent, else adds a new version. The key is
  read via plain Read-Host (visible while you type it, but NOT saved to shell
  history - clear the screen after) and written as raw UTF-8 bytes with NO
  trailing newline (a trailing newline would corrupt the token). The temp file
  holding the key is deleted in a finally, even on error. The script itself
  contains no secret and is safe to commit.
  NOTE: plain Read-Host is used deliberately - Read-Host -AsSecureString uses a
  raw char-by-char console read that breaks clipboard paste (only the first char
  comes through), so the masked variant is unusable for pasting a key.
#>
[CmdletBinding()] param()
$PROJECT = "bidbrain-analytics"
$SECRET  = "glm-api-key"

# Run gcloud so its stderr (e.g. the EXPECTED NOT_FOUND when probing) doesn't get
# promoted to a terminating error under $ErrorActionPreference "Stop" and kill the
# script. Same trick as Test-Probe in setup.ps1. Returns $true iff exit code is 0.
function Test-Gcloud {
    param([Parameter(Mandatory)][string[]]$ArgList)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & gcloud @ArgList 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

Write-Host ""
Write-Host "=== bootstrap $SECRET in project $PROJECT ===" -ForegroundColor Cyan
Write-Host "(Using plain input - -AsSecureString breaks clipboard paste. The key will" -ForegroundColor DarkGray
Write-Host " be visible while you type it; run 'Clear-Host' afterwards. It is NOT saved" -ForegroundColor DarkGray
Write-Host " to shell history.)" -ForegroundColor DarkGray
$tok = Read-Host "Paste the Z.ai / GLM API key"
if (-not $tok) { Write-Host "[X] Empty key - aborting." -ForegroundColor Red; exit 1 }
if ($tok.Length -lt 20) {
    Write-Host "[!] Only $($tok.Length) characters - that looks truncated. Re-run and repaste." -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] Got $($tok.Length) characters." -ForegroundColor Green

# Write the token as raw UTF-8 bytes with NO trailing newline.
$tmp = [System.IO.Path]::GetTempFileName()
try {
    [System.IO.File]::WriteAllBytes($tmp, [System.Text.Encoding]::UTF8.GetBytes($tok))

    # Idempotent: create if absent, else add a new version.
    if (Test-Gcloud @("secrets", "describe", $SECRET, "--project", $PROJECT)) {
        $ok = Test-Gcloud @("secrets", "versions", "add", $SECRET, "--data-file=$tmp", "--project", $PROJECT)
        if ($ok) { Write-Host "[OK] $SECRET already existed; added a new version." -ForegroundColor Green }
        else { Write-Host "[X] Failed to add a new version to $SECRET." -ForegroundColor Red; exit 1 }
    } else {
        $ok = Test-Gcloud @("secrets", "create", $SECRET, "--data-file=$tmp", "--replication-policy=automatic", "--project", $PROJECT)
        if ($ok) { Write-Host "[OK] Created $SECRET." -ForegroundColor Green }
        else { Write-Host "[X] Failed to create $SECRET." -ForegroundColor Red; exit 1 }
    }

    # Verify readable by current identity (prints nothing sensitive).
    if (Test-Gcloud @("secrets", "versions", "access", "latest", "--secret", $SECRET, "--project", $PROJECT)) {
        Write-Host "[OK] Readable. glm-bypass-mode.ps1 will now work for you." -ForegroundColor Green
    } else {
        Write-Host "[!] Stored, but not readable by your identity - check IAM on $SECRET." -ForegroundColor Yellow
    }
}
finally {
    [System.IO.File]::Delete($tmp)
}
Remove-Variable tok -ErrorAction SilentlyContinue
Write-Host ""
