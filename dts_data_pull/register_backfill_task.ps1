# register_backfill_task.ps1
# Registers a daily Windows Scheduled Task that runs backfill_google_ads_history.ps1.
# Idempotent: re-running re-registers the task. The backfill script unregisters this task
# itself once the account's full history is loaded.

$ErrorActionPreference = 'Stop'
$TaskName = 'BidbrainGoogleAdsBackfill'
$Script   = Join-Path $PSScriptRoot 'backfill_google_ads_history.ps1'
$Me       = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$action  = New-ScheduledTaskAction -Execute 'powershell.exe' `
            -Argument "-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$Script`""
$trigger = New-ScheduledTaskTrigger -Daily -At 2pm
# Interactive: runs as the user while they are logged on (no elevation needed to register),
# so gcloud's ADC under %APPDATA%\gcloud is available. -StartWhenAvailable catches up a
# missed run once the user is next logged on.
$principal = New-ScheduledTaskPrincipal -UserId $Me -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
              -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
              -ExecutionTimeLimit (New-TimeSpan -Hours 1)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings `
  -Description 'Auto-continues the Google Ads BigQuery DTS historical backfill, one ~290-day chunk per drain, until all history is loaded.' | Out-Null

Write-Output "Registered scheduled task '$TaskName' (daily 14:00, runs as $Me)."
