# client_schneider/job/ — the export job (stage 2)

A Cloud Run **Job** (`schneider-export`): reads the BigQuery views in [`../sql/`](../sql/README.md)
and writes one `schneider.json` to the private bucket `bidbrain-analytics-schneider-dash`. Then it
exits. The gated web service ([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_STT/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to
GCS, nothing else. It never touches Snowflake (the shared `raw_*` layers are filled by their own
loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "schneider"` → dataset / bucket / object all follow. Reads the delivery roll-ups + the 5 seed tables → `env` dict → JSON. `GA4_ENABLED` (default `False`) gates the `ga4_*` branches. Self-gates on upstream freshness before any rebuild (see below). |
| `freshness.py` | Vendored copy of the shared self-gating helper (`probe_bq_last_modified`, `read_watermark` / `write_watermark`, `is_stale`). Probes BigQuery `__TABLES__.last_modified_time` (metadata-only) and reads/writes the GCS watermark sidecar. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract:** the view column names → `main.py` (the `env` keys) → JSON keys → `dashboard.html`
(`data.*`). Rename a view column → fix `main.py`; rename a JSON key → fix `dashboard.html`.

**GA4 gating:** the `ga4_*` views exist (with a property-id placeholder → 0 rows) but are NOT queried
while `GA4_ENABLED = False`; the payload carries `ga4_enabled:false` and empty `ga4_*` arrays. To
enable: set the real `PROPERTY_ID`(s) in `sql/40_stg_ga4.sql` (+ `46_`), flip `GA4_ENABLED = True`,
reapply views, re-run the job.

**Freshness (self-gating):** the job runs on a `*/10 * * * *` UTC Cloud Scheduler tick
(`schneider-export-daily`) but only rebuilds + re-uploads `schneider.json` when an upstream raw
table it reads has advanced. On each tick it cheaply probes `__TABLES__.last_modified_time` for
`GATING_TABLES` — `raw_snowflake.dv360_apac`, `raw_snowflake.linkedin_ads_apac`,
`raw_snowflake.tradedesk_apac_all` — and compares against the watermark sidecar
`_freshness.json` in the data bucket. No advance → it exits 0 without querying views or uploading;
an advance → it rebuilds, uploads, then writes the new watermark (upload first, watermark second, so
a failed upload simply retries next tick). `FORCE_REBUILD=1` bypasses the gate for manual runs.
`raw_snowflake.google_analytics_apac_all` is deliberately **not** gated (GA4 ships disabled → 0 rows,
so gating on it would only force pointless rebuilds). The dashboard shows `last_updated` (build time)
and `data_through` (newest gated `last_modified`), never a hardcoded refresh time. See the repo
`CLAUDE.md` "Freshness contract".

**Runtime SA** `schneider-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer`
(project, read-only) and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute schneider-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_schneider\job\main.py`).
