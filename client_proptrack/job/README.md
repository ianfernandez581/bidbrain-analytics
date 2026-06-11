# client_proptrack/job/ — the export job (stage 2)

A Cloud Run **Job** (`proptrack-export`): reads the BigQuery views in [`../sql/`](../sql/README.md) and
writes one `proptrack.json` to the private bucket `bidbrain-analytics-proptrack-dash`. Then it exits. The
gated web service ([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_STT/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to GCS,
nothing else. It never touches Snowflake directly (the shared `raw_snowflake` layer is filled by
`snowflake_data_pull/`), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "proptrack"` → dataset / bucket / object all follow. Reads 12 roll-up views → `env` dict → JSON. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract (matched by name):** `sql/*.sql` view column → `main.py` (the `env` dict key) → JSON key →
`dashboard.html` (`DATA.*`). Rename a view column → fix `main.py`; rename a JSON key → fix `dashboard.html`.
All spend keys are `*_spend_aud` — single currency, no FX.

**Runtime SA** `proptrack-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project,
read-only) and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute proptrack-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_proptrack\job\main.py`).
