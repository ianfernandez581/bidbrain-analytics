# backfill_google_ads_history.ps1
# Auto-continues the Google Ads BigQuery Data Transfer Service backfill, walking
# BACKWARD one ~290-day chunk per run, respecting the DTS 300-inflight-runs cap.
# Designed to be run by a daily Windows Scheduled Task (see register_backfill_task.ps1).
#
# Each invocation:
#   1. Counts inflight (PENDING+RUNNING) runs. If still draining (> threshold), does nothing.
#   2. Otherwise finds the oldest data date currently loaded (MIN segments_date).
#   3. If the previous chunk added NO older data (floor didn't move), the account has no
#      more history -> reports COMPLETE and unregisters its own scheduled task.
#   4. Else submits the next [floor-290d, floor) chunk and records the floor it dropped below.
#
# State + log live outside the repo, under %LOCALAPPDATA%\bidbrain-gads-backfill\.

$ErrorActionPreference = 'Stop'

# ---- fixed config (see dts_data_pull/README.md) -----------------------------------------
$BQ        = 'C:\Users\Ian\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\bq.cmd'
$CONFIG    = 'projects/516554645957/locations/australia-southeast1/transferConfigs/6a271b88-0000-2a01-873b-d4f547eea634'
$TABLE     = 'bidbrain-analytics.raw_google_ads.ads_CampaignBasicStats_3451896252'
$DATE_COL  = 'segments_date'
$CHUNK     = 290   # days per backfill request (290 + <=5 inflight stays under the 300 cap)
$INFLIGHT_OK = 5   # only submit a new chunk when inflight has dropped to/below this
$TASK_NAME = 'BidbrainGoogleAdsBackfill'

$StateDir  = Join-Path $env:LOCALAPPDATA 'bidbrain-gads-backfill'
if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir | Out-Null }
$StateFile = Join-Path $StateDir 'state.json'
$LogFile   = Join-Path $StateDir 'backfill.log'

function Log($msg) {
  $line = "$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))  $msg"
  Add-Content -Path $LogFile -Value $line
  Write-Output $line
}

try {
  # 1. inflight count -- PENDING/RUNNING backfill runs carry future scheduleTimes, so they
  #    always sort to the top; a 500-row page reliably captures all <=300 inflight.
  $runsJson = & $BQ ls --transfer_run --max_results=500 --format=json $CONFIG
  $runs = $runsJson | ConvertFrom-Json
  $inflight = @($runs | Where-Object { $_.state -eq 'PENDING' -or $_.state -eq 'RUNNING' }).Count

  if ($inflight -gt $INFLIGHT_OK) {
    Log "draining: $inflight runs inflight (> $INFLIGHT_OK). No action."
    exit 0
  }

  # 2. current oldest loaded data date (the floor)
  $q = "SELECT FORMAT_DATE('%Y-%m-%d', MIN($DATE_COL)) AS d FROM ``$TABLE``"
  $floorJson = & $BQ query --use_legacy_sql=false --format=json $q
  $floor = ($floorJson | ConvertFrom-Json)[0].d
  if ([string]::IsNullOrWhiteSpace($floor)) { Log "could not read MIN($DATE_COL); skipping."; exit 0 }
  $floorDate = [datetime]::ParseExact($floor, 'yyyy-MM-dd', $null)

  # 3. stop condition: did the previous chunk move the floor at all?
  $prevFloor = $null
  if (Test-Path $StateFile) { $prevFloor = (Get-Content $StateFile -Raw | ConvertFrom-Json).lastFloor }

  if ($prevFloor -and $prevFloor -eq $floor) {
    Log "BACKFILL COMPLETE. Earliest available Google Ads data = $floor. Last chunk added no older data; unregistering task '$TASK_NAME'."
    try { Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false } catch { Log "note: could not unregister task: $($_.Exception.Message)" }
    exit 0
  }

  # 4. submit the next chunk backward: [floor-CHUNK, floor)
  $end   = $floorDate.ToString('yyyy-MM-dd') + 'T00:00:00Z'
  $start = $floorDate.AddDays(-$CHUNK).ToString('yyyy-MM-dd') + 'T00:00:00Z'
  Log "drained ($inflight inflight); floor=$floor. Submitting chunk start=$start end=$end ..."
  & $BQ mk --transfer_run --start_time=$start --end_time=$end $CONFIG | Out-Null

  @{ lastFloor = $floor; submittedAtUtc = [DateTime]::UtcNow.ToString('s') } | ConvertTo-Json | Set-Content -Path $StateFile -Encoding utf8
  Log "submitted chunk covering $($floorDate.AddDays(-$CHUNK).ToString('yyyy-MM-dd')) -> $floor. Will resume below $floor next drain."
}
catch {
  Log "ERROR: $($_.Exception.Message)"
  exit 1
}
