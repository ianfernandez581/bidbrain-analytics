# deploy_grid_preview.ps1 - deploy The Grid to a PRIVATE PREVIEW revision that live never sees.
#
# WHY THIS EXISTS. deploy_grid.ps1 sends `central-grid` straight to 100% of traffic, so every
# super-admin sees the change the moment it lands. This script instead creates a TAGGED,
# --no-traffic revision: it gets its OWN url, its OWN SQLite state object and its OWN campaign
# seed, while the stable url (and dashboards.bidbrain.ai/d/central/, which proxies it) keeps
# serving exactly what it served before. Promotion is a traffic flip, not a rebuild.
#
#   .\grid-core\deploy_grid_preview.ps1                 # tag auto-generated, printed at the end
#   .\grid-core\deploy_grid_preview.ps1 -Tag grid-sbx   # your own tag
#   .\grid-core\deploy_grid_preview.ps1 -Seed live      # preview the CODE against the LIVE 88 campaigns
#   .\grid-core\deploy_grid_preview.ps1 -ShareState     # read/write the LIVE state blob (see the warning)
#
# HOW YOU REACH IT. central-grid is IAM-GATED (unlike the client dashboards, which are public
# with their own password screen), so the tagged url will NOT open in a browser on its own and
# the platform proxy points at the STABLE url. Tunnel to it instead - the command is printed at
# the end, and each viewer needs roles/run.invoker:
#     gcloud run services proxy central-grid --region australia-southeast1 --tag <tag> --port 8081
#
# THREE THINGS TO KNOW
#  1. GIT: park, don't ship. merge-branches.ps1 maps grid-core/ -> deploy_grid.ps1, so ANY
#     grid-core change that lands via /ship or /go is deployed to LIVE automatically. Keep
#     preview work on a wip/* branch (/park) - ship and go always skip those. /push + /ship only
#     when you want everyone to have it.
#  2. STATE: isolated by default. The preview gets GRID_STATE_OBJECT=grid-state/preview-*.db, so
#     Sync now / inline CONFIG edits / approvals cannot touch what the other super-admins see.
#     -ShareState points it at the live blob, which is READ-ONLY IN PRACTICE: persist.js writes
#     under an ifGenerationMatch precondition and assumes only one revision runs at a time
#     ("overlap is confined to the seconds around a deploy"), so a write from here can make the
#     LIVE revision's next save fail with generation-conflict. Read freely, do not mutate.
#  3. SERVICE TEMPLATE: this deploy leaves the sandbox env vars ON the service template, because
#     Cloud Run has no per-revision env. Any LATER `gcloud run services update` would therefore
#     build a live revision carrying them and the live Grid would boot the wrong seed.
#     deploy_grid.ps1 now --remove-env-vars all three, so the normal live path self-heals - but
#     do NOT hand-roll a `services update` on central-grid while a preview is outstanding.

param(
    [string]$Tag = "",                                   # revision tag; auto-generated when empty
    [ValidateSet('sandbox','live')][string]$Seed = 'sandbox',  # which campaign snapshot to boot from
    [switch]$ShareState,                                 # use the LIVE state blob instead of a preview copy
    [switch]$NoGreenlight                                # skip Greenlight (it is ON here by default)
)

# ---- config (mirrors deploy_grid.ps1) ----------------------------------------
$PROJECT  = "bidbrain-analytics"
$REGION   = "australia-southeast1"
$REPO     = "bidbrain"
$SERVICE  = "central-grid"
$GRID_DIR = $PSScriptRoot
$SANDBOX_SEED = "config/central-import-sandbox.json"     # in-image path; Charles's 6 live campaigns
$PREVIEW_DUMPS = "bidbrain-campaign-dumps-preview"       # Greenlight uploads; live uses -campaign-dumps
$GL_TIMEOUT = 600                                        # see the Greenlight block below - NOT optional

function Die($m)  { Write-Host "!! Failed: $m." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Die "gcloud not found on PATH" }
if (-not (Test-Path (Join-Path $GRID_DIR 'server.js')))  { Die "no server.js in $GRID_DIR" }
if (-not (Test-Path (Join-Path $GRID_DIR 'Dockerfile'))) { Die "no Dockerfile in $GRID_DIR" }
if ($Seed -eq 'sandbox' -and -not (Test-Path (Join-Path $GRID_DIR $SANDBOX_SEED))) {
    Die "$SANDBOX_SEED is missing - it is baked into the image, so the preview would boot the LIVE seed"
}

# A guessable tag is the whole access story on a url someone might try by hand, so the default
# carries random hex. Cloud Run tags: lowercase letters, digits and hyphens only.
if ([string]::IsNullOrWhiteSpace($Tag)) {
    $rand = -join ((1..6) | ForEach-Object { '0123456789abcdef'[(Get-Random -Maximum 16)] })
    $Tag = "sbx-$rand"
}
$Tag = $Tag.ToLower().Trim()
if ($Tag -notmatch '^[a-z0-9-]+$') { Die "tag '$Tag' must be lowercase letters, digits and hyphens only" }

# The image ships the working tree (same as deploy_grid.ps1) - say so rather than block.
$dirty = (& git -C $GRID_DIR status --porcelain -- . 2>$null)
if ($dirty) { Write-Host "(i) grid-core has uncommitted changes - the preview image includes them:`n$dirty" -ForegroundColor DarkGray }

$branch = "$(& git -C $GRID_DIR rev-parse --abbrev-ref HEAD 2>$null)".Trim()
if ($branch -and $branch -notlike 'wip/*') {
    Write-Host "!! You are on '$branch', not a wip/* branch. If this gets /push-ed, the next /ship by ANYONE" -ForegroundColor Yellow
    Write-Host "   deploys it to LIVE. Park it instead:  .\scripts\park.ps1 -Desc grid-preview" -ForegroundColor Yellow
}

$SHA = $null
try { $SHA = (& git -C $GRID_DIR rev-parse --short HEAD 2>$null) } catch { $SHA = $null }
if (-not $SHA -or $LASTEXITCODE -ne 0) { $SHA = "manual-$(Get-Date -Format 'yyyyMMddHHmmss')" }
$SHA = "$SHA".Trim()

$IMG = "${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:preview-${SHA}"
Write-Host "Building preview image ($SHA) ..." -ForegroundColor Cyan
gcloud builds submit $GRID_DIR --tag $IMG --region $REGION --project $PROJECT; Must "build preview image"

# ---- env for THIS revision ---------------------------------------------------
# Seed: 'sandbox' boots the 14-row snapshot; 'live' leaves CENTRAL_IMPORT_PATH unset so the
# committed central-import.json applies. CENTRAL_EXTRA_PATH is pointed at a path that does not
# exist either way - the scan-sourced extras (HireRight etc.) are noise in a sandbox, and both
# importers in server.js return early when their file is missing.
$envPairs = @("CENTRAL_EXTRA_PATH=/nonexistent/central-extra-campaigns.json")
if ($Seed -eq 'sandbox') { $envPairs += "CENTRAL_IMPORT_PATH=/app/$SANDBOX_SEED" }
if (-not $ShareState)    { $envPairs += "GRID_STATE_OBJECT=grid-state/preview-$Tag.db" }

# GREENLIGHT. Enabled here by default (this preview exists partly to test it) with its OWN dumps
# bucket, so uploaded campaign files + run history never land in the library live reads. Two
# non-obvious requirements:
#   - --timeout 600 is MANDATORY: extraction runs ~320s SYNCHRONOUSLY inside the request and Cloud
#     Run's default 300s cuts it off mid-run. Same reason the documented live enable sets it.
#   - it BILLS. GREENLIGHT_API_KEY is Charles's Kimi Code subscription key (kimi-api-key secret,
#     inherited from the service). Real runs here spend real quota - the preflight (Stage 0) is
#     deterministic, offline and free, so use it before paying for a full run.
# GREENLIGHT_ENABLED is deliberately NOT in deploy_grid.ps1's --remove-env-vars: live already runs
# with the tab ON, and scrubbing it would SWITCH OFF a shipped feature on the next live deploy.
# GREENLIGHT_BUCKET needs no scrub either - deploy_grid.ps1 re-asserts the live bucket explicitly.
if (-not $NoGreenlight) {
    gcloud storage buckets describe "gs://$PREVIEW_DUMPS" --project $PROJECT *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Creating preview dumps bucket gs://$PREVIEW_DUMPS ..." -ForegroundColor Cyan
        gcloud storage buckets create "gs://$PREVIEW_DUMPS" --location $REGION --project $PROJECT --uniform-bucket-level-access; Must "create preview dumps bucket"
    }
    $RUNTIME_SA = "516554645957-compute@developer.gserviceaccount.com"
    gcloud storage buckets add-iam-policy-binding "gs://$PREVIEW_DUMPS" `
        --member="serviceAccount:$RUNTIME_SA" --role="roles/storage.objectAdmin" --project $PROJECT *> $null
    $envPairs += "GREENLIGHT_ENABLED=true"
    $envPairs += "GREENLIGHT_BUCKET=$PREVIEW_DUMPS"
}
$envArg = ($envPairs -join ',')

# --update-secrets RE-ASSERTS the two API keys rather than trusting them to be inherited from the
# service template. `gcloud run deploy` does carry unspecified config forward, so this is belt and
# braces - but Greenlight is DEAD WITHOUT THEM (extraction 401s at the provider), the failure would
# only surface mid-run, and re-asserting is exactly what deploy_grid.ps1 does for the same reason:
# it is idempotent and self-heals a service that somehow lost them. Same secret names as live.
Write-Host "Deploying tagged revision '$Tag' with NO traffic ..." -ForegroundColor Cyan
gcloud run deploy $SERVICE --image $IMG --region $REGION --project $PROJECT `
    --no-traffic --tag $Tag --timeout $GL_TIMEOUT `
    --update-env-vars $envArg `
    --update-secrets "ANTHROPIC_API_KEY=anthropic-api-key:latest,GREENLIGHT_API_KEY=kimi-api-key:latest"; Must "deploy preview revision"

# The tagged url is DERIVED, not queried: Cloud Run builds it as <tag>---<service-host>, so splicing
# it into the stable url needs no second API call and cannot break on a --format expression. (A
# `--format` projection over status.traffic was the first version; it is untestable without a live
# tag, and a wrong one would have printed an empty url after a successful deploy.)
$STABLE = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format "value(status.url)")
$STABLE = "$STABLE".Trim()
# Which revision LIVE is on now - named in the traffic-pinning warning below, so the person running
# this knows exactly what is serving and what to route back to.
$LIVE_REV = (gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format json | ConvertFrom-Json)
$LIVE_REV = @($LIVE_REV.status.traffic | Where-Object { $_.percent -gt 0 } | ForEach-Object { $_.revisionName }) -join ', '
if (-not $LIVE_REV) { $LIVE_REV = '(unknown)' }
$TAGURL = if ($STABLE -match '^https://(.+)$') { "https://$Tag---$($Matches[1])" } else { "(could not derive - run: gcloud run services describe $SERVICE --region $REGION)" }

Write-Host ""
Write-Host "Done. Preview revision '$Tag' is live on 0% of traffic." -ForegroundColor Green
Write-Host "  Seed:          $(if ($Seed -eq 'sandbox') { "$SANDBOX_SEED (14 campaigns)" } else { 'config/central-import.json (live snapshot)' })"
Write-Host "  State:         $(if ($ShareState) { 'SHARED with live - READ ONLY, a write here can block live''s next save' } else { "grid-state/preview-$Tag.db (isolated)" })"
Write-Host "  Greenlight:    $(if ($NoGreenlight) { 'off' } else { "ON - dumps -> gs://$PREVIEW_DUMPS (isolated), request timeout ${GL_TIMEOUT}s, BILLS the Kimi key" })"
Write-Host "  Preview url:   $TAGURL"
Write-Host "  Stable url:    $STABLE   <- unchanged, still what everyone else sees"
Write-Host ""
Write-Host "  Open it (IAM-gated, so tunnel - needs roles/run.invoker):" -ForegroundColor Cyan
Write-Host "      gcloud run services proxy $SERVICE --region $REGION --tag $Tag --port 8081"
Write-Host "      then http://localhost:8081/the-grid.html"
Write-Host ""
Write-Host "  Ship it for real (traffic flip, no rebuild):" -ForegroundColor Cyan
Write-Host "      .\grid-core\deploy_grid.ps1        # rebuilds from main AND scrubs the sandbox env vars"
Write-Host "  Throw it away:" -ForegroundColor Cyan
Write-Host "      gcloud run services update-traffic $SERVICE --region $REGION --remove-tags $Tag"
Write-Host ""
Write-Host "  !! THIS DEPLOY PINNED THE SERVICE'S TRAFFIC to $LIVE_REV." -ForegroundColor Yellow
Write-Host "     --no-traffic stops Cloud Run auto-promoting new revisions, so the NEXT deploy_grid.ps1" -ForegroundColor Yellow
Write-Host "     builds and deploys but LIVE STAYS PUT. That script now detects it and prints the fix;" -ForegroundColor Yellow
Write-Host "     the fix always names a revision explicitly - NEVER --to-latest, which while this" -ForegroundColor Yellow
Write-Host "     preview is the newest revision would promote the PREVIEW to live." -ForegroundColor Yellow
Write-Host "     Live is on $LIVE_REV and stays there until you say otherwise." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Reminder: keep this work PARKED (/park). /ship and /go auto-deploy grid-core to LIVE." -ForegroundColor Yellow
