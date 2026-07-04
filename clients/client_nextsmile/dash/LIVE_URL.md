# Next Smile Australia Dashboard — status

> **ONBOARDING / PLACEHOLDER (as of 2026-07-04).** `client_nextsmile/` is a full, Next Smile Australia-branded
> dashboard scaffold **cloned from `client_geocon`** (Meta paid-media template). No live Next Smile Australia data
> is connected yet, so the dashboard renders a **baked-in SAMPLE payload** (`dash/placeholder.json`,
> flagged `meta.placeholder=true`) behind a "sample data — not connected yet" banner. Nothing is
> deployed on GCP until Monday's onboarding.

**Intended service URL (once deployed):** https://nextsmile-dash-516554645957.australia-southeast1.run.app
**Password (once created):** Secret Manager secret `nextsmile-dash-password`.

## Stand it up (Monday)

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"          # charles@ has no deploy perms
# Phase 1 — placeholder service (serves the sample data behind the banner):
.\clients\client_nextsmile\deploy_nextsmile.ps1
# Portal tile (surgical add to the LIVE registry; no full re-seed):
$env:GCS_BUCKET="bidbrain-analytics-platform-dash"
.\.venv\Scripts\python.exe bidbrain-platform\dash\add_nextsmile_placeholder.py --yes
```

## Go live with real data (Phase 2 — once Next Smile Australia Meta data is connected)

Real data flows in when Next Smile Australia's Meta campaigns (named `Next Smile Australia_*`) reach `raw_windsor.perf_meta` and
`raw_windsor.nextsmile_meta_breakdown` exists (see `../ingest/meta_breakdown_pull.py`). Then:

```powershell
.\clients\client_nextsmile\deploy_nextsmile.ps1 -WithData   # applies views + builds/runs the export job + scheduler
```

The moment the export job writes `nextsmile.json` to the bucket, `main.py` `/data.json` prefers it over
the placeholder and the "sample data" banner clears automatically. Finally flip the portal tile to
`active` (in the admin UI, or re-run the registry add with status `active` + the run.app url).

## What gets deployed

| Thing | Value |
|---|---|
| Project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Raw source (Phase 2) | `raw_windsor.perf_meta` + `raw_windsor.nextsmile_meta_breakdown` |
| Views dataset | `client_nextsmile` |
| Export Job (Phase 2) | `nextsmile-export` (self-gating `*/10` UTC via `nextsmile-export-daily`) |
| Dash Service | `nextsmile-dash` (serves `dashboard.html`; `/data.json` = bucket, else `placeholder.json`) |
| Data bucket / file | `bidbrain-analytics-nextsmile-dash` / `nextsmile.json` |
| Job SA | `nextsmile-dash-job@…` (BQ jobUser + dataViewer, Storage objectAdmin on bucket) |
| Web SA | `nextsmile-dash-web@…` (Storage objectViewer on bucket, Secret accessor) |
| Secrets | `nextsmile-dash-password`, `nextsmile-dash-session-key` |

## To refresh data (Phase 2)

```powershell
# Self-gating: a plain execute rebuilds only if raw_windsor.perf_meta advanced.
gcloud run jobs execute nextsmile-export --region australia-southeast1 --wait
# To force: --update-env-vars FORCE_REBUILD=1
```
