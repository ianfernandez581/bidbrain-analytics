# status_dashboard/job/ — the export job (stage 2)

A Cloud Run **Job** (`status-export`) that assembles ONE `status.json` for the meta dashboard and
writes it to the private bucket `bidbrain-analytics-status-dash`. Then it exits. The **platform
front-door** ([`../../bidbrain-platform/`](../../bidbrain-platform/)) reads that JSON to render its
merged Overview + Data Accuracy tabs (the old standalone `../dash/` service is retired).

Unlike a client export job, this one has **no `sql/` views and no BigQuery dataset of its own**. It
*reads other clients'* resources to answer two questions for every Snowflake-sourced client:

1. **Data Sync Status** — is a stale dashboard *Transmission's* fault (the Snowflake **source** table
   hasn't updated) or *100% Digital's* (our pipeline hasn't ingested/rebuilt)? It probes three stages
   and compares them:
   `Snowflake source LAST_ALTERED` → `BigQuery raw_snowflake.* mirror last_modified` → `<client>.json
   last_updated / data_through`.
2. **Data Accuracy** — does the number on each client dashboard equal the number pulled straight from
   Snowflake? It runs the exact `COUNT`/`SUM`, shows it next to the dashboard's number, and includes the
   query so anyone can reproduce it.

**Clients covered (6, Snowflake-sourced):** mongodb, cloudflare, stt, hireright, schneider, proptrack —
the `CLIENTS` spec in `main.py`. (cityperfume + resetdata + tlm + vmch read Windsor/GA4/Neto/Google-Ads
natively, no Snowflake, so they're out of scope.) Keep this list in sync with `$CLIENT_BUCKETS` in
[`../deploy_status.ps1`](../deploy_status.ps1).

| File | What it is |
|---|---|
| `main.py` | The job. The `CLIENTS` spec (per-client sources + accuracy checks), the freshness probe of both stages, the verdict logic, the gated Snowflake accuracy counts, and the `status.json` writer. No `CLIENT` key / dataset / FX — it reports across all clients. |
| `freshness.py` | Vendored probe helpers (identical to the client jobs'): `probe_snowflake_last_altered` (INFORMATION_SCHEMA.LAST_ALTERED, metadata-only — never resumes `APAC_IN_WH`) and `probe_bq_last_modified` (`__TABLES__.last_modified_time`). Used here for *probing*, not for a `_freshness.json` watermark — see Freshness below. |
| `requirements.txt` | `snowflake-connector-python`, `google-cloud-bigquery`, `google-cloud-storage`, `cryptography`, `google-cloud-secret-manager` (pinned; base shared with `clients/client_cloudflare/job`). No pandas — every accuracy result is a single scalar. |
| `Dockerfile` | `python:3.12.13-slim`, non-root (`appuser`), `COPY main.py freshness.py`, `CMD python main.py`. |
| `deploy_job_status.ps1` | Rebuild + redeploy + run ONLY this job after editing `main.py` / `requirements.txt`. |

There is **no `cloudbuild.yaml`** in this folder (the status dashboard predates the future push-to-main
trigger that the per-client jobs carry).

**Freshness / self-gating.** The `*/15` Cloud Scheduler tick is cheap: the Snowflake `LAST_ALTERED`
freshness probe and the BigQuery `__TABLES__` probe are both metadata-only and never resume the
warehouse, so they run every tick for free. The expensive part — the accuracy `COUNT`/`SUM` queries that
**do** resume `APAC_IN_WH` — self-gates *per client*: a client's numbers are recomputed only when that
client's Snowflake source advanced past the `transmission_latest` recorded in the previous `status.json`
(otherwise the prior numbers are carried forward). So this job's "watermark" is the previous `status.json`
itself, not a `_freshness.json` sidecar. Set `FORCE_REBUILD=1` to recompute every client's counts.

**Reads / writes:** reads Snowflake (metadata + a few scalar aggregates), BigQuery (`raw_snowflake.*`
`__TABLES__` metadata), and each client's `<client>.json` from its private bucket. Writes only
`status.json` to `bidbrain-analytics-status-dash`. Spend is **never** used for an equality check (most
clients FX-convert it) — checks use un-transformed integers: lead counts, impressions, clicks, leads.

**Runtime SA** `status-dash-job@…`: `roles/bigquery.jobUser` + `roles/bigquery.dataViewer`,
`roles/storage.objectAdmin` on the status bucket, `roles/storage.objectViewer` on **every** client
bucket, and `roles/secretmanager.secretAccessor` on the shared `snowflake-bq-key`. The stand-up
([`../deploy_status.ps1`](../deploy_status.ps1)) grants all of these.

Run it: `gcloud run jobs execute status-export --region australia-southeast1 --wait`
(or locally for a dry run: `.\.venv\Scripts\python.exe status_dashboard\job\main.py`).
