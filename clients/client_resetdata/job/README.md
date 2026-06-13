# clients/client_resetdata/job/ — the export job (stage 2)

A Cloud Run **Job** (`resetdata-export`): reads the BigQuery views in [`../sql/`](../sql/README.md) and
writes one `resetdata.json` to the private bucket `bidbrain-analytics-resetdata-dash`. Then it exits. The
gated web service ([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `clients/client_STT/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to GCS,
nothing else. It never touches Snowflake / Windsor / GA4 directly (the shared `raw_*` layers are filled by
their own loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "resetdata"` → dataset / bucket / object all follow. Reads 14 roll-up views → `env` dict → JSON. **Self-gating:** probes the five upstream raw tables it reads (`raw_google_ads.perf_google_ads`, `raw_windsor.perf_meta`, `raw_windsor.perf_the_trade_desk`, `raw_ga4.perf_ga4`, `raw_ga4.perf_ga4_events`) via `freshness.py` and skips the rebuild unless one advanced. `FORCE_REBUILD=1` bypasses the gate. Currency is **AUD** throughout (Google/Meta already AUD; TTD USD→AUD ×1.50, surfaced as `fx_usd_aud`). |
| `freshness.py` | Vendored self-gating helper (shared across jobs): `probe_bq_last_modified` (BQ `__TABLES__.last_modified`), `read_watermark`/`write_watermark` (GCS `_freshness.json` sidecar), `is_stale`. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12.13-slim`, non-root, `CMD python main.py`; `COPY main.py freshness.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger — do NOT run from a laptop, it fails on `iam.serviceaccounts.actAs`). |
| `deploy_job_resetdata.ps1` | Rebuild + deploy + run the job after editing `main.py` (the JSON shape). |

**Contract:** the view column names → `main.py` (`r["sessions"]`… via the roll-up keys) → JSON keys
(`data.kpi.sessions`, `data.monthly[].ad_imps`…) → `dashboard.html`. Rename a view column → fix `main.py`;
rename a JSON key → fix `dashboard.html`. The payload also carries `last_updated` (build time) and
`data_through` (the newest upstream `last_modified`, UTC) — the dashboard shows these instead of a fixed
refresh time.

**Freshness:** Cloud Scheduler `resetdata-export-daily` fires `*/10 * * * *` UTC; each tick is a cheap
metadata probe and only the ticks where an upstream raw table advanced do the full rebuild + upload (then
write the watermark — upload first, watermark second). Most ticks no-op and exit 0.

**Runtime SA** `resetdata-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project,
read-only — covers all three raw datasets at once; do NOT narrow it) and `roles/storage.objectAdmin` on the
data bucket.

Deploy after editing `main.py`: `.\client_resetdata\job\deploy_job_resetdata.ps1`
Run it directly: `gcloud run jobs execute resetdata-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_resetdata\job\main.py`).
