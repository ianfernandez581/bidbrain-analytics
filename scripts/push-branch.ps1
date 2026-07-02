# =============================================================================
# push-branch.ps1 -- commit ALL your local work and push it to THIS machine's
#                    own branch, so it can be integrated via merge-branches.ps1.
#
# Each developer/machine gets its own branch so two people never push to the same
# one. The branch name defaults to this machine's name; override it with your own
# name ONCE (it sticks) so the branch reads like "alex/work" instead of
# "DESKTOP-AB12/work".
#
#   First time, set your name (writes a gitignored scripts/.devname):
#     .\scripts\push-branch.ps1 -Dev alex
#   After that, just:
#     .\scripts\push-branch.ps1                       # -> alex/work
#     .\scripts\push-branch.ps1 -Desc vmch-overview   # -> alex/vmch-overview
#     .\scripts\push-branch.ps1 -Message "WIP nav"    # custom commit message
#
# Then integrate everyone's branches onto main + deploy with:
#     .\scripts\merge-branches.ps1
# (This repo pushes to `origin` -- the live remote; the old `bidbrain` remote is dead.)
# =============================================================================

param(
    [string]$Dev = "",       # your name (slugified). Saved to scripts/.devname on first use.
    [string]$Desc = "",      # short description -> the part after the slash (default "work")
    [string]$Message = ""    # commit message (default "WIP from <name>")
)

# Stay on Continue: git writes ordinary progress to stderr, which "Stop" would treat
# as a terminating error even on success. We gate on $LASTEXITCODE via Must.
$ErrorActionPreference = "Continue"
function Die([string]$m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }
function Must([string]$w) { if ($LASTEXITCODE -ne 0) { Die "$w (exit $LASTEXITCODE)" } }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path   # scripts/ -> repo root
Set-Location $repo

# 1. Resolve the owner name: -Dev (and remember it) > scripts/.devname > this machine's name.
$devFile = Join-Path $PSScriptRoot ".devname"
if (-not [string]::IsNullOrWhiteSpace($Dev)) {
    Set-Content -Path $devFile -Value $Dev.Trim() -Encoding ascii   # remember for next time
} elseif (Test-Path $devFile) {
    $Dev = (Get-Content $devFile -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($Dev)) { $Dev = $env:COMPUTERNAME }

function Slug([string]$s) { return (($s.ToLower() -replace '[^a-z0-9]+', '-').Trim('-')) }
$name = Slug $Dev
if ([string]::IsNullOrWhiteSpace($name)) { Die "could not derive a branch name from '$Dev'" }
$slug = Slug $Desc
if ([string]::IsNullOrWhiteSpace($slug)) { $slug = "work" }
$branch = "$name/$slug"

Write-Host "[push-branch] target branch: $branch" -ForegroundColor Cyan

# 2. Snapshot the current working state onto the branch (create-or-reset to HEAD).
git switch -C $branch
Must "create/switch to $branch"

# 3. Stage everything (new + modified + deleted), including untracked files.
git add -A
Must "git add -A"

# 4. Secret guard (defense in depth -- these are gitignored, but never push them anyway).
#    Mirrors this repo's .gitignore secret patterns (keys, PEMs, credentials, .env, bare *_key).
$staged = (git diff --cached --name-only) -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$secretRe = '(\.env$)|(\.p8$)|(\.pem$)|(\.pub$)|(\.key$)|(-key\.json$)|(credentials.*\.json$)|(service-account.*\.json$)|(_key$)|(/id_rsa$)|(/id_ecdsa$)|(/id_ed25519$)|(^id_rsa$)|(^id_ecdsa$)|(^id_ed25519$)'
$danger = $staged | Where-Object { $_ -imatch $secretRe }
if ($danger) {
    git restore --staged $danger 2>$null
    Die "refusing to commit secret-looking files: $($danger -join ', '). They have been unstaged -- gitignore them (see .gitignore + bidbrain-vault/)."
}

# 5. Commit (skip cleanly if there is nothing to commit; the branch still gets pushed).
if (-not [string]::IsNullOrWhiteSpace((git status --porcelain))) {
    if ([string]::IsNullOrWhiteSpace($Message)) { $Message = "WIP from $name" }
    git commit -m $Message
    Must "commit"
} else {
    Write-Host "[push-branch] nothing new to commit -- pushing the branch as-is." -ForegroundColor Yellow
}

# 6. Prune stale remote-tracking refs first. After a branch is merged-and-deleted on
#    the server, our local origin/<branch> ref lingers; --force-with-lease then leases
#    against that ghost and the push is rejected with "stale info". Pruning clears it so
#    the next push cleanly re-creates the branch. (Non-fatal: offline still pushes below.)
git fetch --prune origin 2>$null

# 7. Push with upstream. --force-with-lease so re-running updates YOUR branch safely
#    (it only overwrites if the remote is where we last saw it -- never clobbers someone else).
git push -u origin $branch --force-with-lease
Must "push $branch"

Write-Host ""
Write-Host "[OK] pushed $branch" -ForegroundColor Green
Write-Host "     Integrate + deploy with:  .\scripts\merge-branches.ps1   (or open a PR to main on GitHub)."
