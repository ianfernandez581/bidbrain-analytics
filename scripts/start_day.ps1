# start_day.ps1  -  bidbrain-analytics morning preflight
# Verifies BOTH credential systems gcloud uses -- and that BOTH are the RIGHT
# account (ian@100.digital) -- plus that the loaders can actually read the Windsor
# key, so nothing surprises you mid-task -- THEN runs the /go flow so you start the
# day aligned with the whole team.
#
#   gcloud CLI creds      -> used by `gcloud secrets ...` (the loaders' key fetch)
#   application-default   -> used by Python client libs (BigQuery)
# These expire independently and your org enforces periodic reauth, so both
# are checked here. This box also silently flips the active account to a different
# org login (info@agoradatadriven.com) that has NO access to bidbrain-analytics, so
# both the CLI account AND the ADC *identity* are pinned to $WANT_ACCOUNT -- a valid
# token for the wrong account 403s everything, and checking only "is there a token"
# missed exactly that.
#
# AUTH IS BROWSER-ONLY. Org session control makes a bare gcloud command that needs to
# refresh an expired credential pop an in-terminal reauth challenge
# ("Please enter your password:", masked -- so it looks like you can't type). We AVOID
# that two ways: (1) every credential PROBE below runs with --quiet, so instead of
# prompting in the terminal it fails cleanly; (2) the re-auth uses
# `gcloud auth login --launch-browser --force` -- the --force is ESSENTIAL: without it
# gcloud sees the account already has (session-expired) creds and takes the in-terminal
# REAUTH shortcut (that password prompt) instead of the browser. --force re-runs the
# FULL browser web flow every time, so you re-authenticate in the browser, never here.
#
# After the creds pass, it runs /go (push-branch.ps1 -> merge-branches.ps1):
# pushes your work to your dev branch, integrates EVERY dev branch, deploys the
# changed services, and fast-forwards your local main to origin/main -- so every
# dev opens the day on the latest main with everyone's work integrated. Skip that
# step with -SkipGo (creds-only preflight).
#
# Lives in:  bidbrain-analytics/scripts/
# Run:               .\scripts\start_day.ps1
#   creds only:      .\scripts\start_day.ps1 -SkipGo
# Or double-click:   scripts\start_day.cmd

param(
    [switch]$SkipGo    # run only the credential preflight; skip the /go integrate + deploy + pull
)

$PROJECT = "bidbrain-analytics"
# The ONLY account with access to bidbrain-analytics. This box silently flips the
# active account to info@agoradatadriven.com (a different org login), which has NO
# access here -- every gcloud/BigQuery call then 403s (USER_PROJECT_DENIED). Both the
# CLI account AND the ADC identity are pinned to this below.
$WANT_ACCOUNT = "ian@100.digital"

Set-Location (Split-Path $PSScriptRoot -Parent)

# Prefer the repo's .venv (created by scripts\setup.ps1); fall back to PATH python.
$PY = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }

# Resolve the EMAIL the current application-default credentials belong to. A valid ADC
# token is not enough -- it must be $WANT_ACCOUNT, or the Python loaders + BigQuery 403.
# gcloud has no "print ADC account", so we ask Google's userinfo endpoint with the token
# (ADC login always carries the userinfo.email scope). Returns $null if no/unverifiable token.
function Get-AdcEmail {
    # --quiet: never let an expired session-controlled ADC pop a terminal reauth
    # password prompt -- fail cleanly instead; the caller re-auths via the browser.
    $t = gcloud auth application-default print-access-token --quiet 2>$null
    if (-not $t) { return $null }
    try {
        $info = Invoke-RestMethod -Uri "https://www.googleapis.com/oauth2/v3/userinfo" `
            -Headers @{ Authorization = "Bearer $t" } -ErrorAction Stop
        return $info.email
    } catch { return $null }
}

Write-Host ""
Write-Host "=== bidbrain-analytics :: start of day ===" -ForegroundColor Cyan
Write-Host "Working dir: $(Get-Location)" -ForegroundColor DarkGray

# 1. gcloud on PATH?
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Host "[X] gcloud not found. Open a fresh terminal or reinstall the Cloud SDK." -ForegroundColor Red
    exit 1
}

# 2. gcloud CLI account -- ENFORCE $WANT_ACCOUNT (this box flips to the agora login).
#    Handle this FIRST so later gcloud calls run as the right identity.
Write-Host "[*] Checking gcloud CLI account..." -ForegroundColor Yellow
$active = "$(gcloud config get-value account 2>$null)".Trim()
if ($active -ne $WANT_ACCOUNT) {
    Write-Host "[!] Active account is '$active' - must be $WANT_ACCOUNT. Switching..." -ForegroundColor Yellow
    $authed = @(gcloud auth list --format="value(account)" 2>$null | ForEach-Object { $_.Trim() })
    if ($authed -contains $WANT_ACCOUNT) {
        gcloud config set account $WANT_ACCOUNT 2>$null | Out-Null
    } else {
        Write-Host "[!] $WANT_ACCOUNT is not logged in - opening browser (sign in as $WANT_ACCOUNT)." -ForegroundColor Yellow
        gcloud auth login $WANT_ACCOUNT --launch-browser --force
        gcloud config set account $WANT_ACCOUNT 2>$null | Out-Null
    }
    $active = "$(gcloud config get-value account 2>$null)".Trim()
}
if ($active -eq $WANT_ACCOUNT) {
    Write-Host "[OK] CLI account = $active" -ForegroundColor Green
} else {
    Write-Host "[X] CLI account is '$active', not $WANT_ACCOUNT. Fix: gcloud auth login $WANT_ACCOUNT" -ForegroundColor Red
    exit 1
}

# 2b. That account's token must be valid (org enforces periodic reauth).
Write-Host "[*] Checking gcloud CLI credentials..." -ForegroundColor Yellow
$cliToken = gcloud auth print-access-token --quiet 2>$null
if (-not $cliToken) {
    Write-Host "[!] gcloud CLI needs reauth (org session policy). Opening browser (sign in as $WANT_ACCOUNT)..." -ForegroundColor Yellow
    gcloud auth login $WANT_ACCOUNT --launch-browser --force
} else {
    Write-Host "[OK] gcloud CLI credentials valid." -ForegroundColor Green
}

# 3. Pin the CLI project so `gcloud secrets` looks in the right place.
gcloud config set project $PROJECT 2>$null | Out-Null
Write-Host "[OK] CLI project = $PROJECT" -ForegroundColor Green

# 4. Application-default credentials (used by the Python client libs / BigQuery).
#    CRITICAL: a valid ADC token is NOT enough -- it must belong to $WANT_ACCOUNT.
#    ADC login silently grabs info@agoradatadriven.com if that's the browser's default
#    Google session, and then every BigQuery/loader call 403s. So verify the ADC
#    *identity*, not just that a token exists (the bug this check was added to catch).
Write-Host "[*] Checking application-default credentials (token + identity)..." -ForegroundColor Yellow
$adcEmail = Get-AdcEmail
if (-not $adcEmail) {
    Write-Host "[!] ADC missing/expired - opening browser (sign in as $WANT_ACCOUNT)." -ForegroundColor Yellow
    gcloud auth application-default login --launch-browser | Out-Null
    $adcEmail = Get-AdcEmail
}
if ($adcEmail -and $adcEmail -ne $WANT_ACCOUNT) {
    Write-Host "[!] ADC is logged in as '$adcEmail', not $WANT_ACCOUNT." -ForegroundColor Yellow
    Write-Host "    Re-running ADC login - in the browser, pick $WANT_ACCOUNT (NOT the agora account)." -ForegroundColor Yellow
    gcloud auth application-default login --launch-browser | Out-Null
    $adcEmail = Get-AdcEmail
}
if ($adcEmail -eq $WANT_ACCOUNT) {
    Write-Host "[OK] ADC identity = $adcEmail" -ForegroundColor Green
} elseif ($adcEmail) {
    Write-Host "[X] ADC is still '$adcEmail', not $WANT_ACCOUNT - BigQuery + the Python loaders will 403." -ForegroundColor Red
    Write-Host "    Fix: gcloud auth application-default login  (choose $WANT_ACCOUNT in the browser)" -ForegroundColor Red
    exit 1
} else {
    Write-Host "[!] Couldn't verify the ADC identity (token unreadable). Continuing - the BigQuery ping below will confirm." -ForegroundColor Yellow
}
gcloud auth application-default set-quota-project $PROJECT 2>$null | Out-Null
Write-Host "[OK] ADC quota project = $PROJECT" -ForegroundColor Green

# 6. Verify the loaders can read the Windsor key (the exact op they do first).
#    Captured to $null so the secret never prints to screen.
Write-Host "[*] Checking Secret Manager (windsor-api-key)..." -ForegroundColor Yellow
$null = gcloud secrets versions access latest --secret windsor-api-key --project $PROJECT --quiet 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Windsor key readable - loaders can authenticate." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't read windsor-api-key. If you weren't prompted to reauth," -ForegroundColor Yellow
    Write-Host "    check the secret name / your IAM access to it." -ForegroundColor Yellow
}

# 6b. Verify the GLM launcher can read the shared key (so a launch doesn't fail
#     mid-task). Captured to $null so the secret never prints.
Write-Host "[*] Checking Secret Manager (glm-api-key for GLM launcher)..." -ForegroundColor Yellow
$null = gcloud secrets versions access latest --secret glm-api-key --project $PROJECT --quiet 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] glm-api-key readable - GLM launcher ready." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't read glm-api-key (GLM launcher won't work until fixed)." -ForegroundColor Yellow
}

# 7. BigQuery ping via the Python client (same path your loaders use).
Write-Host "[*] Pinging BigQuery (raw_windsor)..." -ForegroundColor Yellow
& $PY -c "from google.cloud import bigquery; bigquery.Client(project='$PROJECT').get_dataset('raw_windsor'); print('ok')" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] BigQuery reachable, raw_windsor found." -ForegroundColor Green
} else {
    Write-Host "[!] Couldn't reach raw_windsor via Python (check creds / dataset name)." -ForegroundColor Yellow
}

# 8. Align with the team -- the /go flow: push my work, integrate EVERY dev branch, deploy
#    the changed services, and fast-forward local main to origin/main (the "pull" that keeps
#    every dev aligned). This is exactly what the /go slash command drives, in order:
#    push-branch.ps1 then merge-branches.ps1 (whose final Sync-LocalMain step does the pull).
#    Runs here because it needs the gcloud auth we just verified (deploy) + BigQuery reachable.
#
#    A shell preflight can't resolve a MERGE CONFLICT or a sanity-gate failure (that needs
#    semantic judgment), so if merge-branches STOPS on one, we stop cleanly and tell you to
#    finish it in Claude Code with  /go . Same for a secret the push guard refuses.
if ($SkipGo) {
    Write-Host ""
    Write-Host "[*] -SkipGo: creds-only preflight. Align with the team later via:  .\scripts\merge-branches.ps1" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "=== /go :: push my work -> integrate everyone -> deploy -> pull main ===" -ForegroundColor Cyan

    Write-Host "[*] Pushing my work to my dev branch..." -ForegroundColor Yellow
    & "$PSScriptRoot\push-branch.ps1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] push-branch stopped -- a file likely looks like a secret (see the message above)." -ForegroundColor Yellow
        Write-Host "    Nothing was integrated; your local main is unchanged. Gitignore/move the file, then re-run start_day." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "[*] Integrating all dev branches, deploying changed services, pulling main..." -ForegroundColor Yellow
    & "$PSScriptRoot\merge-branches.ps1"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[!] merge-branches stopped -- most likely a MERGE CONFLICT or a sanity-gate failure." -ForegroundColor Yellow
        Write-Host "    That needs judgment a preflight can't apply. Finish it in Claude Code: open this repo and run  /go" -ForegroundColor Yellow
        Write-Host "    (it resolves each conflict semantically, then lands + deploys + pulls main)." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Aligned -- local main is up to date with the team; changed services deployed." -ForegroundColor Green
}

Write-Host ""
Write-Host "Ready to go. Common commands:" -ForegroundColor Cyan
Write-Host "  $PY ingest/windsor_data_pull/meta/meta_loader.py"
Write-Host "  $PY ingest/windsor_data_pull/tradedesk/tradedesk_loader.py"
Write-Host "  $PY ingest/windsor_data_pull/meta/create_meta_table.py"
Write-Host ""

