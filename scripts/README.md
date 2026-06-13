# scripts/ — onboarding & daily preflight (Windows) + shared ingest deploy

> The "get this repo running on a fresh Windows laptop" helpers, a quick check
> you run at the start of each session so nothing surprises you mid-task, plus the
> one-shot deployer for the shared raw-layer ingest jobs.

**Plain English:** these are convenience scripts for the person operating the platform from a
Windows machine. One sets the laptop up the first time (installs Python + the Google Cloud
tools, logs you in). One is a 10-second morning check that you're still logged in to
Google Cloud, so the data loaders don't fail halfway through. The newest one
([`deploy_ingest_jobs.ps1`](deploy_ingest_jobs.ps1)) builds, deploys, and schedules the four
shared **ingest** Cloud Run jobs that feed every client dashboard — that one *does* touch
production (run as yourself, never via cloudbuild from a laptop). The two `setup`/`start_day`
helpers never touch production beyond logging you in; the cloud serving/export pieces still
build themselves from each unit's own files.

**Where this sits:** `setup.ps1` / `start_day.ps1` prepare your **local machine** to run the
[`windsor_data_pull/`](../windsor_data_pull/) and [`snowflake_data_pull/`](../snowflake_data_pull/)
loaders and the client export jobs — they don't touch production beyond logging you in.
`deploy_ingest_jobs.ps1` is the exception: it deploys the cloud-side raw loaders themselves
(the ingest jobs that those data-pull folders ship as containers).

---

## What's in here

| File | What it does | Run it… |
|---|---|---|
| [`setup.ps1`](setup.ps1) | **One-time machine setup.** Installs Python 3.12 and the Google Cloud SDK if missing (via `winget`), verifies the committed `requirements.txt` files are present, creates an isolated `.venv` and installs deps into it, then logs you in to gcloud (both CLI creds **and** application-default creds), and verifies it can read the Windsor secret + reach BigQuery. **Idempotent.** | once, right after cloning |
| [`start_day.ps1`](start_day.ps1) | **Per-session preflight.** Verifies both credential systems gcloud uses (CLI creds for `gcloud secrets`, and application-default creds for the Python client libraries), pins the project, confirms it can read `windsor-api-key`, and pings BigQuery (`raw_windsor`). Reauths in a browser if anything expired. | start of each work session |
| [`deploy_ingest_jobs.ps1`](deploy_ingest_jobs.ps1) | **Deploy the shared raw-layer ingest jobs.** Builds, deploys, and schedules the four Cloud Run jobs that land data in the shared `raw_*` BigQuery datasets feeding **every** client dashboard. Ensures the `ingest-runner@` service account + least-privilege IAM first (idempotent). `-Only neto\|meta\|tradedesk\|snowflake`, `-SkipBuild`, `-Run`. Run as yourself (never cloudbuild from a laptop). | when you change an ingest loader |
| [`setup.cmd`](setup.cmd) | Double-clickable launcher for `setup.ps1` (runs it with `-ExecutionPolicy Bypass` so you don't fight Windows script policy). | instead of `setup.ps1` if you prefer double-click |
| [`start_day.cmd`](start_day.cmd) | Double-clickable launcher for `start_day.ps1`. | instead of `start_day.ps1` |

---

## How to use

```powershell
# First time on a new machine (from the repo root):
.\scripts\setup.ps1          # or double-click scripts\setup.cmd

# Every session after that:
.\scripts\start_day.ps1      # or double-click scripts\start_day.cmd

# Then run a loader with the venv's Python:
.\.venv\Scripts\python.exe windsor_data_pull\meta\meta_loader.py

# Deploy the shared ingest jobs to the cloud (build + deploy + schedule all four):
.\scripts\deploy_ingest_jobs.ps1
.\scripts\deploy_ingest_jobs.ps1 -Only neto   # just one: neto|meta|tradedesk|snowflake
.\scripts\deploy_ingest_jobs.ps1 -SkipBuild   # redeploy + reschedule without rebuilding
.\scripts\deploy_ingest_jobs.ps1 -Run         # also execute each job once after deploy
```

---

## The shared ingest jobs (`deploy_ingest_jobs.ps1`)

These are the raw-layer loaders that feed **every** client dashboard. They replace the old
"run the loader from a laptop" step — each lands data in a shared `raw_*` BigQuery dataset on a
Cloud Scheduler trigger, staggered **before** the 22:00 UTC `*-export` jobs so every dashboard's
export reads fresh raw data. All run as the shared `ingest-runner@bidbrain-analytics.iam.gserviceaccount.com`
service account in `australia-southeast1`; images go to the shared `bidbrain` Artifact Registry repo.

| Raw target | Cloud Run job | Build context | Schedule (UTC) |
|---|---|---|---|
| `raw_snowflake.*` (Salesforce/TTD/GA/etc, all clients) | `snowflake-ingest` | `snowflake_data_pull` | `*/10 * * * *` — **self-gating** |
| `raw_neto.orders` (City Perfume sales truth) | `neto-orders-ingest` | `neto_data_pull/orders` | `0 21 * * *` |
| `raw_windsor.perf_meta` (Meta, all granted accounts) | `windsor-meta-ingest` | `windsor_data_pull/meta` | `15 21 * * *` |
| `raw_windsor.perf_the_trade_desk` (TTD, per-account + self-heal) | `windsor-tradedesk-ingest` | `windsor_data_pull/tradedesk` | `35 21 * * *` |

- **`snowflake-ingest` is self-gating** per the freshness contract: it runs every 10 minutes,
  but each tick cheaply checks per-table freshness (`raw_snowflake._sync_state`, honoring
  `FORCE_REBUILD=1`) and most ticks are a ~3s no-op. The neto/windsor loaders stay on a fixed
  daily cron, deliberately staggered just before the 22:00 UTC client exports.
- **Google Ads + GA4 are NOT here** — they auto-refresh daily via the native BigQuery Data
  Transfer Service (free, region `au`), so no ingest job is needed.
- **`windsor-tradedesk-ingest` currently exits non-zero** until the TTD connector is re-granted at
  `https://onboard.windsor.ai?datasource=tradedesk` (the Windsor data endpoint is down) — the
  script prints this reminder on completion.

---

## Why two credential systems are checked

gcloud keeps **two** independent logins, and the org enforces periodic reauth on both, so
either can expire without the other:

- **gcloud CLI credentials** — used by `gcloud …` commands, including the `gcloud secrets`
  call the loaders make to fetch the Windsor key.
- **Application Default Credentials (ADC)** — used by the Python client libraries
  (`google-cloud-bigquery`, `-storage`, `-secret-manager`). This is why the committed code is
  portable: it reads secrets via ADC, with **no machine-specific gcloud path** baked in.

`start_day.ps1` checks both up front so you never hit a surprise reauth prompt halfway through
a long loader run.

---

## Notes & gotchas

- **The committed source is portable as-is.** These scripts are a *convenience* — they never
  edit tracked files. On macOS/Linux you don't need them: `python -m venv`, `pip install -r
  requirements.txt`, and `gcloud auth application-default login` are enough (see the root
  [README Quickstart](../README.md#quickstart)).
- **The `.venv` is a dev-only superset.** `setup.ps1` installs both
  [`requirements.txt`](../requirements.txt) (loaders + setup scripts) and
  [`client_mongodb/job/requirements.txt`](../client_mongodb/job/requirements.txt) (the export
  job) into one venv — they pin compatible versions so they coexist. The **dash** web app is
  deliberately excluded (it pins an older `google-cloud-storage` that conflicts). Each Cloud
  Run unit still builds its own container from its own `requirements.txt`, so this local venv
  never affects image builds.
- **`Test-Probe` (in `setup.ps1`):** under `$ErrorActionPreference = "Stop"`, redirecting a
  native command's stderr (`2>$null`) turns expected probe failures into *terminating* errors
  that would abort the whole script. `Test-Probe` drops to `Continue` and judges success purely
  by exit code, so an "expected to fail" check (e.g. not-logged-in) falls through to the login
  step instead of killing the script.
- **Known dangling reference:** the closing hints in `setup.ps1` mention
  `.\scripts\run-export-job.ps1` (a local export-job runner). **That file isn't in the repo
  yet.** To run the MongoDB export job locally today, use the commands in
  [`client_mongodb/README.md`](../client_mongodb/README.md) instead.

## See also

- [Root README](../README.md) — the whole-platform map and the cross-platform Quickstart.
- [`windsor_data_pull/`](../windsor_data_pull/README.md) / [`snowflake_data_pull/`](../snowflake_data_pull/README.md) — what you run *after* setup.
