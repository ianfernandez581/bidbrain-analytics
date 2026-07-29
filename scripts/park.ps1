# =============================================================================
# park.ps1 -- commit + push your WORK-IN-PROGRESS to a parked branch
#             (wip/<dev>/<desc>) WITHOUT shipping it.
#
# Parked branches are EXPLICITLY SKIPPED by merge-branches.ps1 (/ship, /go): work
# on a wip/* branch is never integrated, never lands on main, never deploys. Use
# it at end of day, before switching tasks, or any time you want unfinished work
# safely off this machine without putting it in front of clients.
#
#   Park (first time):     .\scripts\park.ps1                  # -> wip/<dev>/work
#   Park a named feature:  .\scripts\park.ps1 -Desc vmch-nav   # -> wip/<dev>/vmch-nav
#   Re-park (append):      .\scripts\park.ps1                  # adds a commit to the SAME branch
#   Promote (ship it):     /go  (or .\scripts\push-branch.ps1) run FROM the wip branch --
#                          push-branch detects the parked branch, pushes its content to
#                          <dev>/<desc> (the normal integration flow), ship integrates +
#                          deploys it, and the wip branch is deleted.
#
# Where you end up: ON the wip branch, tree clean, WIP committed and pushed. Keep
# working there; /go when it's ready. start_day.ps1 keeps parked branches fresh
# (rebases them onto the latest main each morning) and warns when one has been
# parked more than 7 days.
#
# Never destroys work: everything is committed before any branch move; carrying a
# dirty tree onto an existing park branch goes through a stash whose conflicted
# pop STOPS with the stash intact; the same secret guard as push-branch.ps1 blocks
# key-looking files; pushes use --force-with-lease (needed after start_day's
# rebase -- it only overwrites a remote we have seen, never someone else's push).
#
# Agent-agnostic: /park (.claude/commands/park.md) is a thin Claude Code wrapper;
# any other agent or a human runs this .ps1 directly for identical behavior.
# =============================================================================

param(
    [string]$Dev = "",       # your name (slugified); shares scripts/.devname with push-branch
    [string]$Desc = "",      # short description -> wip/<dev>/<desc> (default "work")
    [string]$Message = ""    # commit message (default "park: WIP from <name>")
)

# Stay on Continue: git writes ordinary progress to stderr, which "Stop" would treat
# as a terminating error even on success. We gate on $LASTEXITCODE via Must.
$ErrorActionPreference = "Continue"
function Die([string]$m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }
function Must([string]$w) { if ($LASTEXITCODE -ne 0) { Die "$w (exit $LASTEXITCODE)" } }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path   # scripts/ -> repo root
Set-Location $repo

# Refuse mid-merge: parking a half-merged tree would freeze conflict markers into the branch.
git rev-parse -q --verify MERGE_HEAD *>$null
if ($LASTEXITCODE -eq 0) { Die "a merge is in progress. Finish it (git add -A; git commit --no-edit) or abort it (git merge --abort) before parking." }

# 1. Resolve the owner name (same rules + same gitignored scripts/.devname as push-branch.ps1).
$devFile = Join-Path $PSScriptRoot ".devname"
if (-not [string]::IsNullOrWhiteSpace($Dev)) {
    Set-Content -Path $devFile -Value $Dev.Trim() -Encoding ascii   # remember for next time
} elseif (Test-Path $devFile) {
    $Dev = (Get-Content $devFile -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($Dev)) { $Dev = $env:COMPUTERNAME }

function Slug([string]$s) { return (($s.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')) }
$name = Slug $Dev
if ([string]::IsNullOrWhiteSpace($name)) { Die "could not derive a name from '$Dev'" }

$cur = "$(git rev-parse --abbrev-ref HEAD 2>$null)".Trim()
$slug = Slug $Desc
if ([string]::IsNullOrWhiteSpace($slug)) {
    # No -Desc: if already on one of MY wip branches, re-park onto it; else default "work".
    if ($cur -like "wip/$name/*") { $slug = ($cur -split '/', 3)[2] } else { $slug = "work" }
}
$branch = "wip/$name/$slug"

Write-Host "[park] target parked branch: $branch" -ForegroundColor Cyan

# 2. Get onto the wip branch WITHOUT losing the working tree.
if ($cur -ne $branch) {
    git show-ref --verify --quiet "refs/heads/$branch"
    $localExists = ($LASTEXITCODE -eq 0)
    $remoteExists = $false
    if (-not $localExists) {
        git fetch origin $branch *>$null
        git rev-parse -q --verify "origin/$branch" *>$null
        $remoteExists = ($LASTEXITCODE -eq 0)
    }
    if (-not $localExists -and -not $remoteExists) {
        git switch -c $branch          # brand-new park: branch created AT HEAD keeps the dirty tree
        Must "create $branch"
    } else {
        # The park branch already exists (locally or on origin): carry the dirty tree over
        # with a stash so re-parking APPENDS instead of resetting. A conflicted pop STOPS
        # with the stash intact -- nothing is ever lost.
        $dirty = -not [string]::IsNullOrWhiteSpace((git status --porcelain))
        if ($dirty) { git stash push -u -m "park-carry" | Out-Null; Must "stash before switching to $branch" }
        if ($localExists) { git switch $branch; Must "switch to $branch" }
        else { git switch -c $branch "origin/$branch"; Must "create $branch from origin/$branch" }
        if ($dirty) {
            git stash pop
            if ($LASTEXITCODE -ne 0) {
                Die "your changes conflict with what is already parked on $branch. NOTHING is lost: the changes are in 'git stash list' (park-carry) and the parked commits are intact. Resolve the conflicts left in the tree, then re-run park (and 'git stash drop' the park-carry entry once it is safely committed)."
            }
        }
    }
}

# 3. Stage everything + secret guard (same patterns as push-branch.ps1 / the ship gate;
#    .example templates like api-probe/.env.example are allowed).
git add -A
Must "git add -A"
$staged = (git diff --cached --name-only) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$secretRe = '((^|/)\.env(\..+)?$)|(\.p8$)|(\.pem$)|(\.pub$)|(\.key$)|(-key\.json$)|(credentials.*\.json$)|(service-account.*\.json$)|(_key$)|((^|/)id_(rsa|ecdsa|ed25519)$)'
$danger = $staged | Where-Object { $_ -imatch $secretRe -and $_ -notmatch '\.example$' }
if ($danger) {
    git restore --staged $danger 2>$null
    Die "refusing to park secret-looking files: $($danger -join ', '). They have been unstaged -- gitignore/move them (see .gitignore + bidbrain-vault/), then re-run."
}

# 4. Commit -- APPENDS to the branch (never resets it), so repeated parks build a history.
if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    if ([string]::IsNullOrWhiteSpace($Message)) { $Message = "park: WIP from $name" }
    git commit -m $Message
    Must "commit"
} else {
    Write-Host "[park] nothing new to commit -- pushing the branch as-is." -ForegroundColor Yellow
}

# 5. Push. --force-with-lease: required after start_day rebases this branch onto fresh
#    main; it only overwrites if the remote is where we last saw it.
git fetch --prune origin 2>$null
git push -u origin $branch --force-with-lease
Must "push $branch"

Write-Host ""
Write-Host "[OK] parked on $branch (pushed; /ship and /go will IGNORE it)" -ForegroundColor Green
Write-Host "     Keep working here. Promote + ship it later by running /go (or .\scripts\push-branch.ps1) from this branch."
