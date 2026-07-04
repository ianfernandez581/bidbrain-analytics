# Caltex Dashboard — status

> **ONBOARDING / PLACEHOLDER (as of 2026-07-04).** `client_caltex/` is a full, Caltex-branded
> dashboard scaffold **cloned from `client_geocon`** (Meta paid-media template). No live Caltex data
> is connected yet, so the dashboard renders a **baked-in SAMPLE payload** (`dash/placeholder.json`,
> flagged `meta.placeholder=true`) behind a "sample data — not connected yet" banner. Nothing is
> deployed on GCP until Monday's onboarding.

**Intended service URL (once deployed):** https://caltex-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `caltex-dash-password`.

## Stand it up (Monday)

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"          # charles@ has no deploy perms
# Phase 1 — placeholder service (serves the sample data behind the banner):
.\clients\client_caltex\deploy_caltex.ps1
# Portal tile (surgical add to the LIVE registry; no full re-seed):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\add_caltex_placeholder.py --yes
```

## Go live with real data (Phase 2 — once Caltex Meta data is connected)

Real data flows in when Caltex's Meta campaigns (named `Caltex_*`) reach `raw_windsor.perf_meta` and
`raw_windsor.caltex_meta_breakdown` exists (see `../ingest/meta_breakdown_pull.py`). Then:

```powershell
.\clients\client_caltex\deploy_caltex.ps1 -WithData   # applies views + builds/runs the export job + scheduler
```

The moment the export job writes `caltex.json` to the bucket, `main.py` `/data.json` prefers it over
the placeholder and the "sample data" banner clears automatically. Finally flip the portal tile to
`active` (in the admin UI, or re-run the registry add with status `active` + the run.app url).

## What gets deployed

| Thing | Value |
|---|---|
| Project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Raw source (Phase 2) | `raw_windsor.perf_meta` + `raw_windsor.caltex_meta_breakdown` |
| Views dataset | `client_caltex` |
| Export Job (Phase 2) | `caltex-export` (self-gating `*/10` UTC via `caltex-export-daily`) |
| Dash Service | `caltex-dash` (serves `dashboard.html`; `/data.json` = bucket, else `placeholder.json`) |
| Data bucket / file | `bidbrain-analytics-caltex-dash` / `caltex.json` |
| Job SA | `caltex-dash-job@…` (BQ jobUser + dataViewer, Storage objectAdmin on bucket) |
| Web SA | `caltex-dash-web@…` (Storage objectViewer on bucket, Secret accessor) |
| Secrets | `caltex-dash-password`, `caltex-dash-session-key` |

## To refresh data (Phase 2)

```powershell
# Self-gating: a plain execute rebuilds only if raw_windsor.perf_meta advanced.
gcloud run jobs execute caltex-export --region australia-southeast1 --wait
# To force: --update-env-vars FORCE_REBUILD=1
```
