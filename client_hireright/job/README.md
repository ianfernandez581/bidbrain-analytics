# client_hireright/job/ — the export job (stage 2)

A Cloud Run **Job** (`hireright-export`): reads the BigQuery views in [`../sql/`](../sql/README.md) and
writes one `hireright.json` to the private bucket `bidbrain-analytics-hireright-dash`. Then it exits. The
gated web service ([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`.

Like `client_STT/job`, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to GCS,
nothing else. It never touches Snowflake directly (the shared `raw_*` layers are filled by their own
loaders), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "hireright"` → dataset / bucket / object all follow. Reads the roll-up views → `env` dict → JSON. Also derives the `markets` filter list (by spend desc). |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12-slim`, non-root, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger). |

**Contract:** the view column names → `main.py` (the roll-up keys) → JSON keys
(`data.kpi.ad_spend_usd`, `data.monthly[].dv_spend_usd`, `data.ad_campaigns[].spend_usd`…) →
`dashboard.html`. Rename a view column → fix `main.py`; rename a JSON key → fix `dashboard.html`.
Spend is **USD** end-to-end (`*_spend_usd` / `*_cost_usd`).

**Runtime SA** `hireright-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project,
read-only) and `roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute hireright-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe client_hireright\job\main.py`).
