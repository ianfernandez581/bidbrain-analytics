# clients/client_cityperfume/job/ — the export job (stage 2)

A Cloud Run **Job** (`cityperfume-export`): reads the BigQuery views in
[`../sql/`](../sql/README.md) and writes one `cityperfume.json` to the private bucket
`bidbrain-analytics-cityperfume-dash`. Then it exits. The gated web service
([`../dash/`](../dash/README.md)) serves that JSON at `/data.json`. Built on the
[`client_STT`](../../client_STT/job/README.md) job pattern.

Like STT, this job is **read-only on BigQuery** — it `SELECT`s views and writes JSON to GCS, nothing
else. It never touches Snowflake or the raw loaders (Google Ads DTS / Windsor / GA4 / Neto fill the
shared `raw_*` layers on their own), so it needs only the BigQuery + Storage clients.

| File | What it is |
|---|---|
| `main.py` | The job. `CLIENT = "cityperfume"` → dataset / bucket / object all follow. A generic `clean()` mapper (Decimal→float, DATE→`YYYY-MM-DD`) makes JSON keys mirror the view columns exactly. Emits **aggregates only** + an `assert_no_pii` guard. |
| `freshness.py` | The shared self-gating helper, vendored per job folder (like `sf_connect` elsewhere). `probe_bq_last_modified`, `read_watermark` / `write_watermark` (GCS sidecar), `is_stale`. No heavy top-level imports so an idle tick stays light. |
| `cityperfume.json` | A captured local dry-run payload (sample shape), not the served object. |
| `requirements.txt` | `google-cloud-bigquery`, `google-cloud-storage` (pinned). |
| `Dockerfile` | `python:3.12.13-slim`, non-root, `COPY main.py freshness.py`, `CMD python main.py`. |
| `cloudbuild.yaml` | Build → push → `run jobs deploy` (for a future push-to-main trigger; deploy as yourself from a laptop). |
| `deploy_job_cityperfume.ps1` | Rebuild + deploy + run **only** the job after a `main.py` JSON-shape change. |

**Contract:** the view column names → `main.py` (the `env` keys) → JSON keys → `dashboard.html`
(`data.*`). Rename a view column → re-run the job; rename a JSON key → fix `dashboard.html`. The
payload carries `last_updated` (build time, UTC), `data_through` (newest upstream `last_modified`, UTC),
`currency: "AUD"`, the headline `kpi`, full-period roll-ups, day-grained arrays (`*_daily`, the
range-filter source), `yoy_monthly`, and verbatim `notes` (attribution stance + GA4/margin caveats).

**Privacy (non-negotiable):** the job reads only the roll-up views (never `v_sales` / `stg_sales`
directly), none of which expose `email` / `customer_id`. Before writing, `assert_no_pii` recursively
scans the payload for forbidden identity keys and refuses to ship if any leak through.

**Freshness — self-gating (`*/10` UTC tick).** On each scheduler tick the job probes
`__TABLES__.last_modified_time` (metadata-only) of the raw tables it reads — `raw_neto.orders`,
`raw_google_ads.perf_google_ads`, `raw_windsor.perf_meta`, `raw_windsor.perf_the_trade_desk`,
`raw_ga4.perf_ga4`, `raw_ga4.perf_ga4_events` — against the `_freshness.json` watermark in the bucket.
It rebuilds + uploads **only** when one advanced past the watermark, otherwise exits 0 without pulling
or uploading. Order matters: **upload first, write the watermark second**, so a failed upload simply
retries next tick. `FORCE_REBUILD=1` bypasses the gate for manual runs. (See the repo CLAUDE.md
"Freshness contract".)

**Runtime SA** `cityperfume-dash-job@bidbrain-analytics.iam.gserviceaccount.com`:
`roles/bigquery.jobUser` + `roles/bigquery.dataViewer` (project, read-only) and
`roles/storage.objectAdmin` on the data bucket.

Run it: `gcloud run jobs execute cityperfume-export --region australia-southeast1 --wait`
(or locally for a dry run: `$env:LOCAL_OUT="cityperfume.json"; .\.venv\Scripts\python.exe client_cityperfume\job\main.py`).
