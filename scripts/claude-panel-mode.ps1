<#
  claude-panel-mode.ps1  -  switch the VS Code Claude extension between GLM and Anthropic
  ---------------------------------------------------------------------------------------
  Bidbrain twin of Agora's agora-devtools/claude-panel-mode.ps1 (which toggles Kimi).
  The VS Code extension spawns its OWN Claude process, so scripts/glm-bypass-mode.ps1
  (which sets env vars for one terminal) never reaches it. The panel's env comes from the
  `claudeCode.environmentVariables` array in VS Code User settings.json
  (%APPDATA%\Code\User\settings.json), read when each panel session spawns.

  This script toggles that block (plus claudeCode.disableLoginPrompt) so you don't edit
  JSON by hand:

    .\scripts\claude-panel-mode.ps1           # show which provider the panel is on
    .\scripts\claude-panel-mode.ps1 glm       # panel -> Z.ai GLM (key from Secret Manager)
    .\scripts\claude-panel-mode.ps1 claude    # panel -> Anthropic (removes the override)

  After EITHER switch: Ctrl+Shift+P -> "Developer: Reload Window" (or restart VS Code),
  then /status in the panel shows the active base URL. There is no way to reload a window
  from outside the process, and killing Code.exe would nuke any running Claude sessions --
  so the reload stays a manual step.

  Notes:
  - MACHINE SCOPE: the setting hits every VS Code window on this machine (incl. the Agora
    window). Agora's panel script writes the SAME block for Kimi -- last writer wins, and
    `status` here reports whichever provider currently owns the override; `claude` removes
    the override no matter which script set it.
  - TERMINAL UNAFFECTED: glm-bypass-mode / plain `claude` keep working per-launch.
  - MODEL SET is a SUPERSET of glm-bypass-mode.ps1's (keep the shared vars in sync!): the
    panel resolves every model slot (opus/sonnet/haiku/fable/subagents), and any slot left
    unset would silently route those calls to Anthropic -- so all slots are pinned here.
  - The token is fetched FRESH from Secret Manager on each switch to glm (never printed);
    switching to claude removes it from the file, so no key sits on disk in Anthropic mode.
  - The settings file is backed up to settings.json.bak-panel-toggle before every write.
  - settings.json is parsed tolerantly (// comments, /* */, and trailing commas outside
    strings are stripped before ConvertFrom-Json) and rewritten as plain JSON, so any
    hand-added comments are lost on write -- values are never touched.
  - Never runs `gcloud config set`; the project is passed explicitly per the repo rule.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('glm', 'claude', 'status')]
    [string]$Mode = 'status',
    [string]$Project = "bidbrain-analytics",
    [string]$Secret  = "glm-api-key"
)

$ErrorActionPreference = "Stop"
$settingsPath = "$env:APPDATA\Code\User\settings.json"

# Base URL + opus/sonnet/haiku values MUST match scripts/glm-bypass-mode.ps1 (keep in sync).
# The extra slots (MODEL/FABLE/SUBAGENT) exist because the panel resolves them independently.
$glmEnv = [ordered]@{
    ANTHROPIC_BASE_URL             = "https://api.z.ai/api/anthropic"
    ANTHROPIC_AUTH_TOKEN           = $null
    ANTHROPIC_MODEL                = "glm-5.2"
    ANTHROPIC_DEFAULT_OPUS_MODEL   = "glm-5.2"
    ANTHROPIC_DEFAULT_SONNET_MODEL = "glm-5.2"
    ANTHROPIC_DEFAULT_HAIKU_MODEL  = "glm-4.7"
    ANTHROPIC_DEFAULT_FABLE_MODEL  = "glm-5.2"
    CLAUDE_CODE_SUBAGENT_MODEL     = "glm-5.2"
}

function Read-JsonTolerant([string]$Path) {
    # ConvertFrom-Json (PS 5.1) rejects JSONC. Try raw first; on failure strip //
    # and /* */ comments and trailing commas -- only when OUTSIDE a string literal.
    $raw = [System.IO.File]::ReadAllText($Path)
    try { return ($raw | ConvertFrom-Json) } catch {}
    $sb = New-Object System.Text.StringBuilder
    $inStr = $false; $esc = $false; $i = 0
    while ($i -lt $raw.Length) {
        $c = $raw[$i]
        if ($inStr) {
            [void]$sb.Append($c)
            if ($esc) { $esc = $false }
            elseif ($c -eq '\') { $esc = $true }
            elseif ($c -eq '"') { $inStr = $false }
            $i++; continue
        }
        if ($c -eq '"') { $inStr = $true; [void]$sb.Append($c); $i++; continue }
        if ($c -eq '/' -and $i + 1 -lt $raw.Length -and $raw[$i + 1] -eq '/') {
            while ($i -lt $raw.Length -and $raw[$i] -ne "`n") { $i++ }
            continue
        }
        if ($c -eq '/' -and $i + 1 -lt $raw.Length -and $raw[$i + 1] -eq '*') {
            $i += 2
            while ($i + 1 -lt $raw.Length -and -not ($raw[$i] -eq '*' -and $raw[$i + 1] -eq '/')) { $i++ }
            $i += 2; continue
        }
        if ($c -eq ',') {
            $j = $i + 1
            while ($j -lt $raw.Length -and [char]::IsWhiteSpace($raw[$j])) { $j++ }
            if ($j -lt $raw.Length -and ($raw[$j] -eq '}' -or $raw[$j] -eq ']')) { $i++; continue }
        }
        [void]$sb.Append($c); $i++
    }
    return ($sb.ToString() | ConvertFrom-Json)
}

function Save-Json($Cfg) {
    Copy-Item $settingsPath "$settingsPath.bak-panel-toggle" -Force
    $json = ConvertTo-Json $Cfg -Depth 10
    [System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-OverrideProvider($Cfg) {
    # Which provider currently owns the panel override (this script or Agora's Kimi twin)?
    if ($null -eq $Cfg.PSObject.Properties['claudeCode.environmentVariables']) { return $null }
    $base = ($Cfg.'claudeCode.environmentVariables' | Where-Object name -eq 'ANTHROPIC_BASE_URL').value
    if ($base -like '*z.ai*')  { return "GLM ($base)" }
    if ($base -like '*kimi*')  { return "KIMI ($base) -- set by the Agora panel script" }
    return "OTHER ($base)"
}

function Show-ReloadInstructions($provider) {
    Write-Host ""
    Write-Host "[DONE] Panel = $provider" -ForegroundColor Green
    Write-Host "       Apply it:  Ctrl+Shift+P -> 'Developer: Reload Window'  (or restart VS Code)" -ForegroundColor Yellow
    Write-Host "       Verify:    /status in the Claude panel shows the active base URL"
    Write-Host "       Scope:     ALL VS Code windows on this machine (incl. the Agora window)" -ForegroundColor DarkGray
    Write-Host "       Terminal:  unaffected -- glm-bypass-mode / plain claude unchanged" -ForegroundColor DarkGray
}

if (-not (Test-Path $settingsPath)) {
    Write-Host "[X] $settingsPath not found -- is VS Code (stable) installed for this user?" -ForegroundColor Red
    exit 1
}

$cfg = Read-JsonTolerant $settingsPath
$owner = Get-OverrideProvider $cfg

switch ($Mode) {
    'status' {
        if ($owner) { Write-Host "Panel = $owner" -ForegroundColor Green }
        else        { Write-Host "Panel = CLAUDE (Anthropic, no env override)" -ForegroundColor Cyan }
        Write-Host "Terminal sessions pick their own launcher (glm-bypass-mode / plain claude)." -ForegroundColor DarkGray
        return
    }
    'glm' {
        if ($owner -like 'GLM*') {
            Write-Host "[=] Panel is already on GLM -- nothing to do." -ForegroundColor Yellow
            Write-Host "    (To refresh the token, e.g. after a key rotation: switch to claude, then back to glm.)" -ForegroundColor DarkGray
            return
        }
        if ($owner) { Write-Host "[!] Replacing the existing panel override: $owner" -ForegroundColor Yellow }
        # fetch the key fresh (same pattern as glm-bypass-mode.ps1; never printed)
        Write-Host "[*] Reading $Secret from Secret Manager (project $Project)..." -ForegroundColor Yellow
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $tok = $null
        try { $tok = (gcloud secrets versions access latest --secret $Secret --project $Project 2>$null) } catch {}
        $ErrorActionPreference = $prevEAP
        if (-not $tok) {
            Write-Host "[X] Could not read '$Secret' from project '$Project' (gcloud auth? IAM? see glm-bypass-mode.ps1)." -ForegroundColor Red
            exit 1
        }
        $glmEnv['ANTHROPIC_AUTH_TOKEN'] = ([string]$tok).Trim()
        $envVars = foreach ($k in $glmEnv.Keys) { [pscustomobject]@{ name = $k; value = $glmEnv[$k] } }
        $cfg | Add-Member -NotePropertyName 'claudeCode.disableLoginPrompt' -NotePropertyValue $true -Force
        $cfg | Add-Member -NotePropertyName 'claudeCode.environmentVariables' -NotePropertyValue @($envVars) -Force
        Save-Json $cfg
        Show-ReloadInstructions "GLM (glm-5.2 / haiku glm-4.7)"
        return
    }
    'claude' {
        if (-not $owner) {
            Write-Host "[=] Panel is already on Claude -- nothing to do." -ForegroundColor Yellow
            return
        }
        $cfg.PSObject.Properties.Remove('claudeCode.environmentVariables')
        $cfg.PSObject.Properties.Remove('claudeCode.disableLoginPrompt')
        Save-Json $cfg
        Show-ReloadInstructions "CLAUDE (Anthropic)"
        return
    }
}
