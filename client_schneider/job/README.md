# client_schneider/job/ — the export job (stage 2)

A Cloud Run **Job** (`schneider-export`): reads the BigQuery views in [`../sql/`](../sql/README.md)
and writes one `schneider.json` to the private bucket `bidbrain-analytics-schneider-dash`. Then it
exits. The gated web service ([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_STT/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to
GCS, nothing else. It never touches Snowflake (the shared `raw_*` layers are filled by their own
loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "schneider"` → dataset / bucket / object all follow. Reads the delivery roll-ups + the 5 seed tables → `env` dict → JSON. `GA4_ENABLED` (default `False`) gates the `ga4_*` branches. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract:** the view column names → `main.py` (the `env` keys) → JSON keys → `dashboard.html`
(`data.*`). Rename a view column → fix `main.py`; rename a JSON key → fix `dashboard.html`.

**GA4 gating:** the `ga4_*` views exist (with a property-id placeholder → 0 rows) but are NOT queried
while `GA4_ENABLED = False`; the payload carries `ga4_enabled:false` and empty `ga4_*` arrays. To
enable: set the real `PROPERTY_ID`(s) in `sql/40_stg_ga4.sql` (+ `46_`), flip `GA4_ENABLED = True`,
reapply views, re-run the job.

**Runtime SA** `schneider-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer`
(project, read-only) and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute schneider-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_schneider\job\main.py`).
