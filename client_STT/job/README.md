# client_STT/job/ — the export job (stage 2)

A Cloud Run **Job** (`stt-export`): reads the BigQuery views in [`../sql/`](../sql/README.md) and writes
one `stt.json` to the private bucket `bidbrain-analytics-stt-dash`. Then it exits. The gated web service
([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_mongodb/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to
GCS, nothing else. It never touches Snowflake or Windsor directly (the shared `raw_*` layers are filled
by their own loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "stt"` → dataset / bucket / object all follow. Reads 19 roll-up views → `env` dict → JSON. Self-gating: probes the four upstream `raw_snowflake.*_apac` tables via `freshness.py` and skips the rebuild unless one advanced. |
| `freshness.py` | Vendored self-gating helper (shared across jobs): `probe_bq_last_modified` (BQ `__TABLES__.last_modified`), `read_watermark`/`write_watermark` (GCS `_freshness.json` sidecar), `is_stale`. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract:** the view column names → `main.py` (`r["SESSIONS"]`… via the roll-up keys) → JSON keys
(`data.kpi.sessions`, `data.monthly[].ad_imps`…) → `dashboard.html`. Rename a view column → fix `main.py`;
rename a JSON key → fix `dashboard.html`.

**Freshness (self-gating, `*/10` UTC):** Cloud Scheduler `stt-export-daily` runs every 10 minutes, but
each tick first does a metadata-only `__TABLES__.last_modified` probe of the four `raw_snowflake.*_apac`
tables this job reads (`google_analytics_apac_all`, `google_ads_apac`, `linkedin_ads_apac`, `dv360_apac`)
and compares against the `_freshness.json` watermark sidecar in the bucket. It rebuilds + uploads **only
when an upstream advanced** — otherwise it exits 0 without touching BigQuery or GCS. Set `FORCE_REBUILD=1`
to bypass the gate for a manual run. The watermark is written **after** a successful upload, so a failed
upload simply retries next tick. The JSON carries `last_updated` (build time) and `data_through` (newest
upstream `last_modified`, UTC) — the dashboard shows these instead of a hardcoded refresh time.

**Runtime SA** `stt-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project, read-only)
and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute stt-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_STT\job\main.py`).
