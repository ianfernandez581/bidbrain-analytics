# =============================================================================
# merge-branches.ps1 -- integrate the per-developer branches, land them on main,
#                       and DEPLOY every changed service to live. One command, end to
#                       end. The agent (Claude Code) is the human-in-the-loop: this
#                       script does the deterministic, mechanical work and STOPS for the
#                       agent only where judgment is needed (a real merge conflict, a
#                       broken tree). Everything else -- land + auto-detect-and-deploy
#                       + prune -- is automatic.
#
# == AGENT RUNBOOK (read this when a developer drops this file into Claude Code) =======
#   The team SOP is: a developer pastes the path to this script into Claude Code and asks
#   you to "merge + deploy". You (the agent) DRIVE THE WHOLE PIPELINE TO LIVE:
#
#     1. Run it:   .\scripts\merge-branches.ps1
#        (optionally .\scripts\merge-branches.ps1 -DryRun FIRST to print the land+deploy
#         plan and change nothing -- good when you're unsure what will ship.)
#
#     2. If it STOPS on a MERGE CONFLICT: it LEAVES the conflict in the working tree (it does
#        NOT abort). Open the conflicting files, resolve them SEMANTICALLY -- preserve BOTH
#        developers' intent (e.g. two people who edited the same dashboard.html); never just
#        pick one side blindly. Then commit + continue:
#            git add -A; git commit --no-edit
#            .\scripts\merge-branches.ps1 -Resume
#        -Resume KEEPS your resolution and carries on (it doesn't rebuild the integration from
#        scratch), so the loop converges. Repeat until it stops stopping.
#
#     3. If it STOPS on the SANITY GATE: the integrated tree has a leftover conflict marker,
#        a Python syntax error, or invalid JSON (usually a botched conflict resolution). Fix
#        it on the integrated tree, then `git add -A; git commit --no-edit` and re-run with
#        -Resume. NEVER land a tree that fails the gate.
#        (NOTE: this repo has no unit-test/CI suite, so the gate is a syntax + merge-sanity
#         check, not a behavioural test. Deploy scripts still rebuild + run the export jobs.)
#
#   ONE-CLICK: developers don't run this by hand -- they use the /ship slash command
#   (.claude/commands/ship.md), which tells you (the agent) to run it and drive the whole
#   resolve -> commit -> -Resume loop automatically. /push wraps push-branch.ps1.
#
#     4. On success it has ALREADY: landed `integration/merge` into `main` (fast-forward,
#        pushed), deployed every service whose files changed (see the mapping below), and
#        pruned the dev branches now contained in `main`. Report to the developer exactly
#        which services deployed and to which URLs.
#
#   You are the only "judgment" in the loop -- the script never auto-resolves a conflict
#   and never lands or deploys a tree that failed the gate. Do not work around those stops.
# =====================================================================================
#
# WHAT IT DOES (default, no flags):
#   0. if your working tree has local changes, commit + push them to THIS machine's own
#      dev branch first (delegates to push-branch.ps1) so your work is integrated too.
#   1. fetch + discover every per-developer branch on origin (everything except main).
#   2. create a throwaway `integration/merge` branch off origin/main.
#   3. merge each branch in turn -- on the FIRST conflict it LEAVES the conflict in the tree
#      and STOPS (hand off to the agent per the runbook above; resolve + commit + -Resume).
#   4. run the local SANITY GATE against the integrated result; STOP if anything is broken.
#   5. LAND: fast-forward `main` to the integrated result and push origin main.
#   6. DEPLOY: diff the integrated result against the old main, map each changed path to
#      its deploy script, and run each (build-as-yourself -> gcloud run deploy). See the
#      path -> deploy-script mapping in Resolve-DeployPlan below.
#   7. PRUNE: delete the remote dev branches whose commits are now contained in origin/main
#      (safe by construction -- it can never drop unmerged work).
#   8. PULL: leave the LOCAL checkout on main and fast-forwarded to origin/main, so your
#      VS Code is completely aligned with what just landed (--ff-only, never clobbers work).
#
# FLAGS (opt out of pieces of the pipeline):
#   -DryRun        do steps 1-4 locally, then PRINT the land + deploy + prune plan and
#                  change NOTHING on origin or in production. (Reflects COMMITTED branches;
#                  commit/push local WIP first to see it in the plan.)
#   -NoPush        integrate + gate, then STOP before landing (review-first). Prints the
#                  manual land/deploy commands.
#   -NoDeploy      land to main, but do NOT deploy the changed services (deploy later).
#   -NoPrune       skip the branch cleanup at the end.
#   -Exclude a,b   skip specific dev branches (comma-separated).
#   -Resume        continue an integration you've been resolving (after resolving a conflict
#                  or a gate failure and committing) -- keeps your commits, skips already-
#                  merged branches, re-gates, then lands + deploys. This is what makes the
#                  conflict loop converge; the /ship command drives it for you.
#   -DeleteMerged  standalone: ONLY prune remote branches already contained in origin/main
#                  (runs nothing else).
#
# USAGE
#   .\scripts\merge-branches.ps1                  # integrate -> land -> deploy -> prune
#   .\scripts\merge-branches.ps1 -DryRun          # preview the whole plan, change nothing
#   .\scripts\merge-branches.ps1 -NoPush          # integrate + gate, then stop for review
#   .\scripts\merge-branches.ps1 -Exclude alex/wip
#   .\scripts\merge-branches.ps1 -DeleteMerged    # prune-only
# =============================================================================

param(
    [string]$Exclude = "",
    [switch]$DeleteMerged,
    [switch]$NoPush,
    [switch]$NoDeploy,
    [switch]$NoPrune,
    [switch]$DryRun,
    [switch]$Resume     # continue an integration you've been resolving (keeps your commits)
)

$ErrorActionPreference = "Continue"
function Die([string]$m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }
function Must([string]$w) { if ($LASTEXITCODE -ne 0) { Die "$w (exit $LASTEXITCODE)" } }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path   # scripts/ -> repo root
Set-Location $repo

$origBranch = (git rev-parse --abbrev-ref HEAD 2>$null)   # remembered so -DryRun can restore it

# A merge left in progress from a previous conflict run: don't silently stomp it. Either
# finish it and -Resume, or abort it and start fresh -- never proceed over it blindly.
git rev-parse -q --verify MERGE_HEAD *>$null
if ($LASTEXITCODE -eq 0 -and -not $Resume) {
    Die "a merge is in progress (unresolved conflict from a previous run). Resolve it then 'git add -A; git commit --no-edit' and re-run with -Resume, or 'git merge --abort' to discard it and start fresh."
}

# -DryRun integrates locally; it never commits your WIP, so a dirty tree would block the
# integration checkout. Require a clean tree for the preview (the real run commits first).
if ($DryRun -and -not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    Die "-DryRun needs a clean working tree (it won't commit your changes). Commit/stash first, or run without -DryRun (the live flow commits your WIP to your dev branch automatically)."
}

# -----------------------------------------------------------------------------
# Map the files that changed in this merge to the deploy script(s) that ship them.
# This is the SINGLE SOURCE OF TRUTH for "what gets deployed when X changes". Each
# changed path matches at most one rule; the scripts are deduped and run in `Prio`
# order (client SQL -> job -> dash, then dash_total/sample, then platform, ingest,
# status). Paths that map to nothing (docs, READMEs, scripts/, root files) are
# correctly ignored. See CLAUDE.md "Redeploy after an edit".
# -----------------------------------------------------------------------------
function Resolve-DeployPlan {
    # Returns an ARRAY (possibly empty) of @{Service; Script; Prio}, deduped by Script,
    # sorted by Prio. NO closures / no outer-state mutation -- each rule just EMITS a row
    # to the pipeline (the closure-mutates-an-ArrayList pattern silently no-ops when this
    # function runs inside the larger script, so it is deliberately avoided here).
    param([string[]]$Changed, [string]$RepoRoot)

    # For a path <baseDir>/..., find the deploy_*.ps1 in <baseDir> by glob (works for any
    # client key without re-typing it -- incl. geocon's mongodb-named deploy scripts and
    # cityperfume's dash_total fork). Returns a row, or $null if none.
    function DirRow([string]$relDir, [string]$service, [string]$pattern, [int]$prio) {
        $dir = Join-Path $RepoRoot $relDir
        if (-not (Test-Path $dir)) { return $null }
        $f = Get-ChildItem -Path $dir -Filter $pattern -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($f) { return [pscustomobject]@{ Service = $service; Script = $f.FullName; Prio = $prio } }
        Write-Host "    [skip] $service changed but no $pattern in $relDir" -ForegroundColor Yellow
        return $null
    }

    $rows = foreach ($cf in $Changed) {
        $p = ($cf -replace '\\', '/')
        # ---- per-client dashboards: clients/client_<c>/{sql,job,dash,dash_total} ----------
        if     ($p -match '^clients/client_STT/client_Adriatic_Furniture/') { DirRow 'clients/client_STT/client_Adriatic_Furniture' "client 'stt' (Adriatic sample dash)" 'deploy_dash_*.ps1' 40 }
        elseif ($p -match '^clients/(client_[^/]+)/sql/')          { $c = $Matches[1]; DirRow "clients/$c/sql"  "client '$($c -replace '^client_','')' (sql views)" 'deploy_views_*.ps1' 10 }
        elseif ($p -match '^clients/(client_[^/]+)/create_views\.py$') { $c = $Matches[1]; DirRow "clients/$c/sql" "client '$($c -replace '^client_','')' (views applier)" 'deploy_views_*.ps1' 10 }
        elseif ($p -match '^clients/(client_[^/]+)/job/')          { $c = $Matches[1]; DirRow "clients/$c/job"  "client '$($c -replace '^client_','')' (export job)" 'deploy_job_*.ps1'   20 }
        elseif ($p -match '^clients/(client_[^/]+)/dash_total/')   { $c = $Matches[1]; DirRow "clients/$c/dash_total" "client '$($c -replace '^client_','')' (total dash fork)" 'deploy_dash_*.ps1' 35 }
        elseif ($p -match '^clients/(client_[^/]+)/dash/')         { $c = $Matches[1]; DirRow "clients/$c/dash" "client '$($c -replace '^client_','')' (dash service)" 'deploy_dash_*.ps1' 30 }
        # ---- committed seed inputs: a targets/ CSV change re-seeds ONLY via the client's -----
        #      seed script (seed_static.py / load_seeds.py) then a FORCE_REBUILD job run --
        #      NEITHER create_views.py NOR the job does it automatically, so we must NOT
        #      silently "deploy" (that would rebuild JSON against STALE seed tables). NOTE it.
        elseif ($p -match '^clients/(client_[^/]+)/targets/') {
            $c = $Matches[1] -replace '^client_',''
            Write-Host "    [note] seed inputs changed for client '$c' (targets/). Re-materialise the seed then rebuild:" -ForegroundColor Yellow
            Write-Host "           .\.venv\Scripts\python.exe clients\$($Matches[1])\seed_static.py   (schneider: load_seeds.py)" -ForegroundColor Yellow
            Write-Host "           gcloud run jobs execute $c-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait" -ForegroundColor Yellow
        }
        # ---- platform front-door (dashboards.bidbrain.ai) -----------------------------------
        elseif ($p -match '^bidbrain-platform/dash/')  { [pscustomobject]@{ Service = 'platform-dash (front-door + proxy)';   Script = (Join-Path $RepoRoot 'bidbrain-platform/dash/deploy_dash_platform.ps1'); Prio = 50 } }
        # ---- shared ingest jobs (raw_snowflake / raw_windsor / raw_neto writers) ------------
        elseif ($p -match '^ingest/')                   { [pscustomobject]@{ Service = 'shared ingest jobs (redeploys all 5)';  Script = (Join-Path $RepoRoot 'scripts/deploy_ingest_jobs.ps1'); Prio = 60 } }
        # ---- status pipeline: the export + deploy JOBS are live; the standalone web dash ----
        #      is RETIRED (its UI is merged into platform-dash), so status_dashboard/dash/
        #      is intentionally NOT deployable here -- redeploy the platform instead.
        elseif ($p -match '^status_dashboard/job/')     { [pscustomobject]@{ Service = 'status-export (job)';                   Script = (Join-Path $RepoRoot 'status_dashboard/job/deploy_job_status.ps1'); Prio = 65 } }
        elseif ($p -match '^status_dashboard/deploy/')  { [pscustomobject]@{ Service = 'status-deploy (job)';                   Script = (Join-Path $RepoRoot 'status_dashboard/deploy/deploy_job_status_deploy.ps1'); Prio = 66 } }
        elseif ($p -match '^status_dashboard/dash/')    { Write-Host "    [note] status_dashboard/dash/ changed but the standalone status web dash is RETIRED (UI merged into platform-dash). Redeploy the platform if its status views moved." -ForegroundColor Yellow }
        # else: docs/, READMEs, scripts/ (incl. these tools + standup deploy_<c>.ps1),
        #       assets, repo-root files -> nothing to deploy.
    }

    # Drop nulls, keep only deploy scripts that exist, dedupe by Script path, sort by Prio.
    $seen = @{}
    $out = foreach ($r in (@($rows) | Where-Object { $_ } | Sort-Object Prio)) {
        if (-not (Test-Path $r.Script)) { Write-Host "    [skip] $($r.Service) -- deploy script missing: $($r.Script)" -ForegroundColor Yellow; continue }
        if ($seen.ContainsKey($r.Script)) { continue }
        $seen[$r.Script] = $true
        $r
    }
    return @($out)
}

# -----------------------------------------------------------------------------
# The SANITY GATE. This repo has no unit-test/CI suite, so we can't run behavioural
# tests. Instead we deterministically reject an integrated tree that is OBVIOUSLY
# broken -- the failure modes a bad merge / botched conflict resolution actually
# produces: leftover conflict markers, Python that won't parse, JSON that won't load.
# Returns $true if the tree is clean, $false (with detail printed) if it must not land.
# -----------------------------------------------------------------------------
function Invoke-SanityGate {
    param([string[]]$Changed, [string]$RepoRoot)
    $ok = $true

    # Only content-check files that still EXIST on the integrated tree (skip deletions).
    $present = $Changed | ForEach-Object { $_ } | Where-Object { $_ -and (Test-Path (Join-Path $RepoRoot $_)) }

    # 1. Leftover conflict markers (a resolution that still has <<<<<<< / >>>>>>> lines).
    #    Only the angle markers -- '=======' also appears legitimately (RST/markdown rules).
    $conflicted = @()
    foreach ($rel in $present) {
        $full = Join-Path $RepoRoot $rel
        if (Select-String -Path $full -Pattern '^(<{7}|>{7}) ' -List -ErrorAction SilentlyContinue) { $conflicted += $rel }
    }
    if ($conflicted.Count -gt 0) {
        Write-Host "    [FAIL] leftover merge-conflict markers in:" -ForegroundColor Red
        foreach ($f in $conflicted) { Write-Host "           $f" -ForegroundColor Red }
        $ok = $false
    }

    # 2. Python syntax: ast.parse every changed .py in ONE interpreter call (no bytecode
    #    written). Prefer the repo venv; fall back to python/py on PATH; warn+skip if none.
    $pyFiles = @($present | Where-Object { $_ -match '\.py$' } | ForEach-Object { Join-Path $RepoRoot $_ })
    if ($pyFiles.Count -gt 0) {
        $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
        if (-not $py) { $py = (Get-Command py -ErrorAction SilentlyContinue).Source }
        if ($py) {
            # utf-8-sig: strip an optional leading BOM (Windows editors add one) so a
            # BOM-prefixed but otherwise-valid .py doesn't false-fail on U+FEFF.
            $chk = "import ast,sys" + "`n" + "for p in sys.argv[1:]:" + "`n" + "    ast.parse(open(p,encoding='utf-8-sig').read(),p)"
            $out = & $py -c $chk @pyFiles 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "    [FAIL] Python syntax error in a changed file:" -ForegroundColor Red
                $out | ForEach-Object { Write-Host "           $_" -ForegroundColor Red }
                $ok = $false
            }
        } else {
            Write-Host "    [warn] no python found (.venv or PATH) -- skipping the Python syntax check" -ForegroundColor Yellow
        }
    }

    # 3. JSON validity: parse every changed .json (definitions.json, platform.json, etc.).
    #    Validate with the repo's Python (a hard dependency here) so it works on BOTH Windows
    #    PowerShell 5.1 and pwsh 7 AND tolerates legitimately-valid JSON that uses empty-string /
    #    duplicate keys (e.g. npm package-lock.json v2/v3 keys the root package as ""). We used to
    #    pipe to `ConvertFrom-Json -AsHashTable`, but -AsHashTable is pwsh-7-only: on WinPS 5.1 (the
    #    primary local dev shell) it throws a parameter-binding error and FALSE-FAILS every JSON
    #    change. Python's json.load keeps-last on dup keys + accepts "" keys (matching that intent);
    #    genuinely invalid JSON (syntax errors, leftover conflict markers) still exits non-zero and
    #    fails the gate. utf-8-sig strips any BOM.
    $py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path $py)) { $py = 'python' }
    $jsonFiles = @($present | Where-Object { $_ -match '\.json$' })
    foreach ($rel in $jsonFiles) {
        $err = & $py -c "import json,sys`njson.load(open(sys.argv[1], encoding='utf-8-sig'))" (Join-Path $RepoRoot $rel) 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Host "    [FAIL] invalid JSON: $rel -- $err" -ForegroundColor Red; $ok = $false }
    }

    return $ok
}

# Per-developer dev branches whose commits are ALREADY in origin/main (safe to delete).
# CRITICAL: exclude the origin/HEAD symref -- its `:short` form is the bare "origin",
# which is not a real branch; trying to delete it errors out and aborts the prune.
function Get-MergedDevBranches([string[]]$Skip) {
    git branch -r --merged origin/main --format='%(refname:short)' |
        Where-Object { $_ -and $_ -ne 'origin/HEAD' -and $_ -ne 'origin' -and $_ -notlike '*->*' } |
        ForEach-Object { ($_ -replace '^origin/', '').Trim() } |
        Where-Object { $_ -and ($Skip -notcontains $_) -and ($_ -notlike 'integration/*') }
}

# Delete remote branches one at a time, never aborting the batch if one is already gone.
function Remove-RemoteBranches([string[]]$Branches) {
    foreach ($b in $Branches) {
        git push origin --delete $b 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "    deleted origin/$b" -ForegroundColor Yellow }
        else { Write-Host "    [warn] could not delete origin/$b (already gone?)" -ForegroundColor Yellow }
    }
}

# Bring the LOCAL checkout fully in line with origin/main so VS Code reflects exactly what
# is on main -- switch to main and fast-forward to the freshly-fetched origin/main. This is
# the "pull" the developer asked for. --ff-only guarantees it can NEVER clobber local work:
# it no-ops when main is already current, fast-forwards when behind, and merely WARNS (never
# force-moves) if local main has somehow diverged.
function Sync-LocalMain {
    Write-Host "[..] Pulling: aligning local main with origin/main (so VS Code matches main)" -ForegroundColor Cyan
    git fetch origin *>$null
    git switch main 2>$null
    if ($LASTEXITCODE -ne 0) { Write-Host "    [warn] could not switch to local main -- skipping pull" -ForegroundColor Yellow; return }
    git merge --ff-only origin/main 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "[OK] local main aligned with origin/main ($(git rev-parse --short HEAD))" -ForegroundColor Green }
    else { Write-Host "    [warn] local main has diverged from origin/main -- NOT fast-forwarding (resolve manually)" -ForegroundColor Yellow }
}

# =============================================================================
# -DeleteMerged is a standalone, GATED cleanup -- it never runs the merge.
# =============================================================================
$skip = @("main", "HEAD") + (($Exclude -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ })

if ($DeleteMerged) {
    Write-Host "[..] Fetching origin" -ForegroundColor Cyan
    git fetch origin --prune; Must "git fetch"
    Write-Host "[..] Deleting remote branches already contained in origin/main" -ForegroundColor Cyan
    $alreadyMerged = @(Get-MergedDevBranches $skip)
    if (-not $alreadyMerged) { Write-Host "    (none are fully merged into main yet -- nothing to delete)" -ForegroundColor Yellow; exit 0 }
    Remove-RemoteBranches $alreadyMerged
    Write-Host "[OK] pruned: $($alreadyMerged -join ', ')" -ForegroundColor Green
    exit 0
}

# =============================================================================
# 0. Capture any local working changes BEFORE we touch branches (commit + push to this
#    machine's own dev branch via push-branch.ps1) so they get integrated below.
#    Skipped under -DryRun (DryRun must not mutate the remote).
# =============================================================================
if ($DryRun) {
    Write-Host "[dry-run] NOT pushing local changes -- the plan reflects COMMITTED branches only." -ForegroundColor Yellow
    if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
        Write-Host "[dry-run] (you have uncommitted changes; commit/push them to see them in the plan)" -ForegroundColor Yellow
    }
} elseif (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    Write-Host "[..] Local changes detected -- committing + pushing them to your branch first" -ForegroundColor Cyan
    & (Join-Path $PSScriptRoot "push-branch.ps1")
    Must "push-branch (commit + push local changes)"
    Write-Host "[OK] local work pushed -- it will be integrated below" -ForegroundColor Green
}

# =============================================================================
# 1-3. Discover dev branches, (re)build the integration branch, and merge each one.
#      Default: rebuild `integration/merge` fresh off the current origin/main.
#      -Resume: continue the integration you've been resolving (keeps your commits) --
#               so a conflict/gate fix you committed is NOT thrown away on re-run.
# =============================================================================
$intg = "integration/merge"

if ($Resume) {
    $cur = (git rev-parse --abbrev-ref HEAD 2>$null); $cur = "$cur".Trim()
    if ($cur -ne $intg) { Die "-Resume expects to be on '$intg' but HEAD is '$cur'. Re-run WITHOUT -Resume to start a fresh integration." }
    if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
        Die "-Resume needs a clean tree. Finish the resolution first:  git add -A; git commit --no-edit   (or 'git merge --abort' to discard it), then re-run -Resume."
    }
    Write-Host "[..] Resuming the in-progress integration on $intg" -ForegroundColor Cyan
    git fetch origin --prune; Must "git fetch"
    $baseMain = (git merge-base origin/main $intg 2>$null); $baseMain = "$baseMain".Trim()
    if ([string]::IsNullOrWhiteSpace($baseMain)) { Die "could not find the base of $intg -- re-run WITHOUT -Resume." }
} else {
    Write-Host "[..] Fetching origin" -ForegroundColor Cyan
    git fetch origin --prune; Must "git fetch"
    $baseMain = (git rev-parse origin/main).Trim()   # the main we are integrating ON TOP OF
    Must "resolve origin/main"
}

$branches = git branch -r --format='%(refname:short)' |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -like 'origin/*' } |
    ForEach-Object { $_ -replace '^origin/', '' } |
    Where-Object { $_ -and ($skip -notcontains $_) -and ($_ -notlike 'integration/*') -and ($_ -ne 'HEAD') }

if (-not $branches) {
    Write-Host "[OK] no dev branches to merge -- origin/main is already current." -ForegroundColor Green
    Sync-LocalMain   # nothing to integrate, but still pull so the LOCAL checkout matches origin/main
    exit 0
}
Write-Host "[OK] branches to integrate: $($branches -join ', ')"

if (-not $Resume) {
    Write-Host "[..] Creating $intg off origin/main" -ForegroundColor Cyan
    git switch -C $intg origin/main; Must "create $intg"
}

# Merge each branch NOT already contained in the integration. On a conflict we LEAVE it in
# the working tree (never abort) so the agent can resolve it in place, commit, and re-run
# with -Resume -- which keeps that commit and continues from here. Converges for both
# textual conflicts and semantic/gate fixes (any committed fix survives the resume).
$merged = @()
foreach ($b in $branches) {
    git merge-base --is-ancestor "origin/$b" HEAD 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "    [skip] $b already integrated" -ForegroundColor DarkGray; $merged += $b; continue }

    Write-Host "[..] Merging $b" -ForegroundColor Cyan
    git merge --no-ff -m "Merge $b into $intg" "origin/$b"
    if ($LASTEXITCODE -ne 0) {
        if ($DryRun) {
            # DryRun must leave no state behind: abort the conflict + restore, don't hand off.
            git merge --abort *>$null
            Write-Host "[dry-run] $b conflicts with the integration -- can't preview past it (resolve it in a real run)." -ForegroundColor Yellow
            if ($origBranch -and $origBranch -ne 'HEAD' -and $origBranch -ne $intg) { git switch $origBranch *>$null } else { git switch main *>$null }
            git branch -D $intg *>$null
            exit 1
        }
        $unmerged = @(git diff --name-only --diff-filter=U | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        Write-Host ""
        Write-Host "[CONFLICT] $b does not merge cleanly -- the conflict is LEFT IN THE TREE for you to resolve." -ForegroundColor Red
        Write-Host "  Conflicted file(s):" -ForegroundColor Yellow
        $unmerged | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        Write-Host "  Already integrated: $($merged -join ', ')" -ForegroundColor Yellow
        Write-Host "  AGENT: resolve each file semantically (preserve BOTH devs' intent), then run:" -ForegroundColor Yellow
        Write-Host "         git add -A; git commit --no-edit" -ForegroundColor Yellow
        Write-Host "         .\scripts\merge-branches.ps1 -Resume   (keeps your resolution + continues; also -Resume after fixing a gate failure)" -ForegroundColor Yellow
        exit 1
    }
    $merged += $b
}
Write-Host "[OK] all branches integrated: $($merged -join ', ')" -ForegroundColor Green

# =============================================================================
#    Compute the changed set ONCE (used by the gate, -DryRun, -NoPush and deploy).
# =============================================================================
$changed = git diff --name-only $baseMain $intg | ForEach-Object { $_.Trim() } | Where-Object { $_ }

# =============================================================================
# 4. SANITY GATE: reject an obviously-broken integrated tree before trusting it.
# =============================================================================
Write-Host "[..] Running the local sanity gate (conflict markers + Python syntax + JSON) against the integrated tree" -ForegroundColor Cyan
if (-not (Invoke-SanityGate -Changed $changed -RepoRoot $repo)) {
    Die "sanity gate FAILED -- do NOT land this. AGENT: fix the failure(s) above on the integrated tree, then re-run. The $intg branch holds the result."
}
Write-Host "[OK] sanity gate passed" -ForegroundColor Green

# =============================================================================
#    Compute the deploy plan now (used by -DryRun, -NoPush, and the live path).
# =============================================================================
$plan = @(Resolve-DeployPlan -Changed $changed -RepoRoot $repo)   # @() => always a real array

# =============================================================================
# -NoPush / -DryRun: stop here. Print exactly what WOULD happen, change nothing live.
# =============================================================================
if ($NoPush -or $DryRun) {
    Write-Host ""
    $tag = if ($DryRun) { "[dry-run]" } else { "[no-push]" }
    Write-Host "$tag $intg is clean + passed the gate. It was NOT landed or deployed." -ForegroundColor Green
    Write-Host "$tag would LAND:   git switch main; git merge --ff-only $intg; git push origin main"
    if ($plan.Count -gt 0) {
        Write-Host "$tag would DEPLOY (changed services):"
        foreach ($s in $plan) { Write-Host "           - $($s.Service)  ->  $($s.Script)" }
    } else {
        Write-Host "$tag would DEPLOY: (nothing -- no deployable service changed)"
    }
    Write-Host "$tag would PRUNE:  dev branches once contained in main (.\scripts\merge-branches.ps1 -DeleteMerged)"
    if ($DryRun) {
        # Restore the branch we started on and drop the throwaway integration branch.
        if ($origBranch -and $origBranch -ne 'HEAD' -and $origBranch -ne $intg) { git switch $origBranch *>$null } else { git switch main *>$null }
        git branch -D $intg *>$null
    }
    exit 0
}

# =============================================================================
# 5. LAND: fast-forward main to the integrated result and push.
# =============================================================================
Write-Host "[..] Landing $intg into main" -ForegroundColor Cyan
git switch main;                 Must "switch to main"
git merge --ff-only origin/main; Must "sync local main to origin/main"   # no-op if already current
git merge --ff-only $intg;       Must "fast-forward main to $intg"
git push origin main;            Must "push origin main"
Write-Host "[OK] landed -- main is now $(git rev-parse --short HEAD)" -ForegroundColor Green

# =============================================================================
# 6. DEPLOY every changed service to live (unless -NoDeploy).
# =============================================================================
if ($NoDeploy) {
    Write-Host "[OK] -NoDeploy: skipping deploy. Changed services that would have deployed:" -ForegroundColor Yellow
    foreach ($s in $plan) { Write-Host "      - $($s.Service)  ->  $($s.Script)" }
} elseif ($plan.Count -eq 0) {
    Write-Host "[OK] no deployable service changed -- nothing to deploy." -ForegroundColor Green
} else {
    # Validate the gcloud token UP FRONT (not just that an account is configured) -- an
    # expired token only fails deep inside the build, after main is already landed. Print-
    # access-token is a cheap, side-effect-free probe that fails fast if reauth is needed.
    # --quiet: under org session control this probe must NEVER pop an in-terminal reauth
    # password prompt -- it fails cleanly instead, and we tell you to `gcloud auth login`
    # (browser) below rather than hanging on a masked terminal prompt.
    $acct = (gcloud config get-value account 2>$null)
    $null = gcloud auth print-access-token --quiet 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($acct) -or $acct -eq '(unset)') {
        Write-Host "[ERROR] gcloud is not authenticated (account='$acct', token invalid)." -ForegroundColor Red
        Write-Host "        main is already landed ($(git rev-parse --short HEAD)) -- nothing was deployed yet." -ForegroundColor Yellow
        Write-Host "        Run 'gcloud auth login', then deploy the service(s) below DIRECTLY:" -ForegroundColor Yellow
        foreach ($s in $plan) { Write-Host "          $($s.Script)" }
        exit 1
    }
    Write-Host "[..] Deploy plan ($($plan.Count) service(s), as $acct):" -ForegroundColor Cyan
    foreach ($s in $plan) { Write-Host "      - $($s.Service)  ->  $($s.Script)" }
    for ($i = 0; $i -lt $plan.Count; $i++) {
        $s = $plan[$i]
        Write-Host ""
        Write-Host "[..] Deploying $($s.Service)" -ForegroundColor Cyan
        & $s.Script
        if ($LASTEXITCODE -ne 0) {
            # main is already landed, so the change is IN main -- re-running THIS script finds
            # no diff and will NOT redeploy. The correct recovery is to run the remaining
            # deploy script(s) directly after fixing the cause.
            Write-Host "[ERROR] deploy FAILED for $($s.Service) (exit $LASTEXITCODE)." -ForegroundColor Red
            Write-Host "        main is already landed ($(git rev-parse --short HEAD)); the change is IN main, so re-running" -ForegroundColor Yellow
            Write-Host "        merge-branches.ps1 will NOT redeploy. Fix the cause, then run the remaining script(s) directly:" -ForegroundColor Yellow
            for ($j = $i; $j -lt $plan.Count; $j++) { Write-Host "          $($plan[$j].Script)" }
            exit 1
        }
        Write-Host "[OK] deployed $($s.Service)" -ForegroundColor Green
    }
    Write-Host "[OK] all changed services deployed." -ForegroundColor Green
}

# =============================================================================
# 7. PRUNE: delete the dev branches now contained in origin/main (unless -NoPrune).
# =============================================================================
if (-not $NoPrune) {
    git fetch origin --prune *>$null
    $alreadyMerged = @(Get-MergedDevBranches $skip)
    if ($alreadyMerged.Count -gt 0) {
        Write-Host ""
        Write-Host "[..] Pruning dev branches now contained in main: $($alreadyMerged -join ', ')" -ForegroundColor Cyan
        Remove-RemoteBranches $alreadyMerged
        Write-Host "[OK] pruned." -ForegroundColor Green
    }
}

# =============================================================================
# 8. PULL: leave the LOCAL checkout on main and fast-forwarded to origin/main, so the
#    developer's VS Code is completely aligned with what just landed (no-op on the happy
#    path, where main was already advanced + pushed above -- but guarantees it on every run).
# =============================================================================
Sync-LocalMain

Write-Host ""
Write-Host "[OK] DONE -- integrated, landed on main, deployed, pruned, and local main pulled." -ForegroundColor Green
