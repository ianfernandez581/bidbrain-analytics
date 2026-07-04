# Bell Shakespeare Dashboard — status

> **ONBOARDING / PLACEHOLDER (as of 2026-07-04).** `client_bellshakespeare/` is a full, Bell Shakespeare-branded
> dashboard scaffold **cloned from `client_geocon`** (Meta paid-media template). No live Bell Shakespeare data
> is connected yet, so the dashboard renders a **baked-in SAMPLE payload** (`dash/placeholder.json`,
> flagged `meta.placeholder=true`) behind a "sample data — not connected yet" banner. Nothing is
> deployed on GCP until Monday's onboarding.

**Intended service URL (once deployed):** https://bellshakespeare-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `bellshakespeare-dash-password`.

## Stand it up (Monday)

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"          # charles@ has no deploy perms
# Phase 1 — placeholder service (serves the sample data behind the banner):
.\clients\client_bellshakespeare\deploy_bellshakespeare.ps1
# Portal tile (surgical add to the LIVE registry; no full re-seed):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\add_bellshakespeare_placeholder.py --yes
```

## Go live with real data (Phase 2 — once Bell Shakespeare Meta data is connected)

Real data flows in when Bell Shakespeare's Meta campaigns (named `Bell Shakespeare_*`) reach `raw_windsor.perf_meta` and
`raw_windsor.bellshakespeare_meta_breakdown` exists (see `../ingest/meta_breakdown_pull.py`). Then:

```powershell
.\clients\client_bellshakespeare\deploy_bellshakespeare.ps1 -WithData   # applies views + builds/runs the export job + scheduler
```

The moment the export job writes `bellshakespeare.json` to the bucket, `main.py` `/data.json` prefers it over
the placeholder and the "sample data" banner clears automatically. Finally flip the portal tile to
`active` (in the admin UI, or re-run the registry add with status `active` + the run.app url).

## What gets deployed

| Thing | Value |
|---|---|
| Project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Raw source (Phase 2) | `raw_windsor.perf_meta` + `raw_windsor.bellshakespeare_meta_breakdown` |
| Views dataset | `client_bellshakespeare` |
| Export Job (Phase 2) | `bellshakespeare-export` (self-gating `*/10` UTC via `bellshakespeare-export-daily`) |
| Dash Service | `bellshakespeare-dash` (serves `dashboard.html`; `/data.json` = bucket, else `placeholder.json`) |
| Data bucket / file | `bidbrain-analytics-bellshakespeare-dash` / `bellshakespeare.json` |
| Job SA | `bellshakespeare-dash-job@…` (BQ jobUser + dataViewer, Storage objectAdmin on bucket) |
| Web SA | `bellshakespeare-dash-web@…` (Storage objectViewer on bucket, Secret accessor) |
| Secrets | `bellshakespeare-dash-password`, `bellshakespeare-dash-session-key` |

## To refresh data (Phase 2)

```powershell
# Self-gating: a plain execute rebuilds only if raw_windsor.perf_meta advanced.
gcloud run jobs execute bellshakespeare-export --region australia-southeast1 --wait
# To force: --update-env-vars FORCE_REBUILD=1
```
