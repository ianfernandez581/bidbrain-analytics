# setup_kb_sync_auth.ps1 - one-shot, idempotent setup so GitHub Actions can sync this repo's
# markdown into the knowledge base, WITHOUT a service-account key existing anywhere.
#
#   HOW TO RUN (once, from the repo root):
#       .\scripts\setup_kb_sync_auth.ps1
#   If you get "running scripts is disabled on this system":
#       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
#
# What it provisions (all idempotent): APIs -> a dedicated kb-sync service account -> least-privilege
# IAM (see below) -> a workload identity pool + OIDC provider trusting GitHub, PINNED TO THIS REPO ->
# the binding that lets this repo's workflow impersonate the service account -> the two repository
# variables the workflow reads. Nothing here issues a key, so there is no key to leak or rotate.
#
# THE ATTRIBUTE CONDITION IS THE WHOLE SECURITY BOUNDARY. A workload identity provider without
# one trusts GitHub's token issuer, which means EVERY repository on GitHub, including one somebody
# creates this afternoon. gcloud refuses to create a provider without a condition for exactly this
# reason; do not "fix" a condition error by widening it.
#
# THE CI IDENTITY MUST NOT BE ABLE TO READ platform.json. It lives in the same bucket and holds
# every client dashboard's password. So object write is granted with an IAM CONDITION scoped to the
# kb/ prefix, and listing - which is checked against the BUCKET and so cannot carry that condition -
# comes from a custom role holding that one permission and nothing else. Use -BroadStorage only if
# an org policy blocks conditional bindings, and know what you are turning off.
#
# After this: push any markdown change to main, or run the workflow by hand from the Actions tab.
# The sync itself is scripts\kb_repo_sync.py and needs none of this to run from a laptop.

param(
  [string]$Repo = "ianfernandez581/bidbrain-analytics",   # owner/name, the repo Actions runs in
  [switch]$BroadStorage,                                  # skip the conditional grant (see above)
  [switch]$SkipGhVariables                                # do not try to set the repo variables
)

# ---- config -----------------------------------------------------------------
$PROJECT   = "bidbrain-analytics"
$BUCKET    = "bidbrain-analytics-platform-dash"     # private; holds kb/ AND the registry JSON
$KB_PREFIX = "kb"
$SA_ID     = "kb-sync"
$SA        = "${SA_ID}@${PROJECT}.iam.gserviceaccount.com"
$POOL      = "github"
$PROVIDER  = "github-oidc"
$LIST_ROLE = "kbSyncObjectList"                     # custom role: storage.objects.list, nothing else

function Die($m)  { Write-Host "!! Failed: $m. Fix the cause and re-run (idempotent)." -ForegroundColor Red; exit 1 }
function Must($m) { if ($LASTEXITCODE -ne 0) { Die $m } }
function Exists($sb) { & $sb *> $null; return ($LASTEXITCODE -eq 0) }

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) { Write-Error "gcloud not found."; exit 1 }
if ($Repo -notmatch '^[^/]+/[^/]+$') { Write-Error "-Repo must be owner/name."; exit 1 }

Write-Host "Setting up keyless knowledge-base sync for $Repo -> $PROJECT`n"

# ---- 1. APIs ----------------------------------------------------------------
Write-Host "[1/6] Enabling APIs ..."
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com iam.googleapis.com `
  aiplatform.googleapis.com storage.googleapis.com --project $PROJECT
Must "enable APIs"

$PROJECT_NUMBER = (gcloud projects describe $PROJECT --format="value(projectNumber)")
Must "read project number"
$PROJECT_NUMBER = $PROJECT_NUMBER.Trim()

# ---- 2. The sync service account --------------------------------------------
# Deliberately NOT platform-dash-web: a CI identity and the service's runtime identity should be
# revocable independently, and this one needs Vertex, which the web service does not.
Write-Host "[2/6] Service account ..."
if (-not (Exists { gcloud iam service-accounts describe $SA --project $PROJECT })) {
  gcloud iam service-accounts create $SA_ID --project $PROJECT `
    --display-name "Knowledge base sync (GitHub Actions)"; Must "create $SA_ID"
  Start-Sleep -Seconds 8   # a brand-new SA is not immediately visible to the IAM policy APIs
}

# ---- 3. IAM: Vertex, plus the narrowest storage grant that works -------------
Write-Host "[3/6] IAM ..."
gcloud projects add-iam-policy-binding $PROJECT --member="serviceAccount:${SA}" `
  --role="roles/aiplatform.user" --condition=None | Out-Null; Must "grant aiplatform.user"

if ($BroadStorage) {
  Write-Host "    -BroadStorage: granting objectAdmin over the WHOLE bucket (incl. platform.json)" -ForegroundColor Yellow
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" `
    --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin" | Out-Null
  Must "grant objectAdmin"
} else {
  if (-not (Exists { gcloud iam roles describe $LIST_ROLE --project $PROJECT })) {
    gcloud iam roles create $LIST_ROLE --project $PROJECT `
      --title "KB sync - list objects" `
      --description "Enumerate objects so the sync can diff the library. No read, no write." `
      --permissions "storage.objects.list" --stage GA | Out-Null; Must "create $LIST_ROLE"
  }
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" `
    --member="serviceAccount:${SA}" --role="projects/${PROJECT}/roles/${LIST_ROLE}" | Out-Null
  Must "grant $LIST_ROLE"

  # Read and write, ONLY under kb/. The resource-name form for an object is
  # projects/_/buckets/<bucket>/objects/<name> - note the literal underscore.
  $cond = "expression=resource.name.startsWith('projects/_/buckets/${BUCKET}/objects/${KB_PREFIX}/'),title=kb_prefix_only,description=Knowledge base objects only"
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" `
    --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin" --condition="$cond" | Out-Null
  Must "grant conditional objectAdmin"
}

# ---- 4. Workload identity pool + provider, pinned to this repo ---------------
Write-Host "[4/6] Workload identity ..."
if (-not (Exists { gcloud iam workload-identity-pools describe $POOL --location global --project $PROJECT })) {
  gcloud iam workload-identity-pools create $POOL --location global --project $PROJECT `
    --display-name "GitHub Actions"; Must "create pool"
}
if (-not (Exists { gcloud iam workload-identity-pools providers describe $PROVIDER --workload-identity-pool $POOL --location global --project $PROJECT })) {
  gcloud iam workload-identity-pools providers create-oidc $PROVIDER `
    --location global --workload-identity-pool $POOL --project $PROJECT `
    --display-name "GitHub OIDC" `
    --issuer-uri "https://token.actions.githubusercontent.com" `
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" `
    --attribute-condition "assertion.repository == '${Repo}'"
  Must "create OIDC provider"
}

$POOL_PATH = "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
$WIF_PROVIDER = "${POOL_PATH}/providers/${PROVIDER}"

# Only this repository may impersonate the sync account. Narrow it further to one branch with
# attribute.ref/refs/heads/main if you ever want that; the workflow only runs on main anyway.
gcloud iam service-accounts add-iam-policy-binding $SA --project $PROJECT `
  --role "roles/iam.workloadIdentityUser" `
  --member "principalSet://iam.googleapis.com/${POOL_PATH}/attribute.repository/${Repo}" | Out-Null
Must "bind workloadIdentityUser"

# ---- 5. Tell the workflow where to find it ----------------------------------
Write-Host "[5/6] Repository variables ..."
if ($SkipGhVariables -or -not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Host "    Set these two in GitHub (Settings > Secrets and variables > Actions > Variables):" -ForegroundColor Yellow
  Write-Host "      GCP_WIF_PROVIDER = $WIF_PROVIDER"
  Write-Host "      GCP_SYNC_SA      = $SA"
} else {
  gh variable set GCP_WIF_PROVIDER --repo $Repo --body "$WIF_PROVIDER"; Must "set GCP_WIF_PROVIDER"
  gh variable set GCP_SYNC_SA      --repo $Repo --body "$SA";           Must "set GCP_SYNC_SA"
  Write-Host "    Set GCP_WIF_PROVIDER and GCP_SYNC_SA on $Repo."
}

# ---- 6. What to do next ------------------------------------------------------
Write-Host "`n[6/6] Done. First load, from this machine:" -ForegroundColor Green
Write-Host "    gcloud auth application-default login"
Write-Host "    .\.venv\Scripts\python.exe scripts\kb_repo_sync.py --dry-run"
Write-Host "    .\.venv\Scripts\python.exe scripts\kb_repo_sync.py --yes"
Write-Host "`nAfter that every push to main that touches a .md file syncs itself."
Write-Host "Verify the CI identity can do what it needs, and no more:"
Write-Host "    gcloud storage buckets get-iam-policy gs://${BUCKET} --format=json"
