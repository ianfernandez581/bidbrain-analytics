# client_STT/job/ — the export job (stage 2)

A Cloud Run **Job** (`stt-export`): reads the BigQuery views in [`../sql/`](../sql/README.md) and writes
one `stt.json` to the private bucket `bidbrain-analytics-stt-dash`. Then it exits. The gated web service
([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_mongodb/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to
GCS, nothing else. It never touches Snowflake or Windsor directly (the shared `raw_*` layers are filled
by their own loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "stt"` → dataset / bucket / object all follow. Reads 18 roll-up views → `env` dict → JSON. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract:** the view column names → `main.py` (`r["SESSIONS"]`… via the roll-up keys) → JSON keys
(`data.kpi.sessions`, `data.monthly[].ad_imps`…) → `dashboard.html`. Rename a view column → fix `main.py`;
rename a JSON key → fix `dashboard.html`.

**Runtime SA** `stt-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project, read-only)
and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute stt-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_STT\job\main.py`).
