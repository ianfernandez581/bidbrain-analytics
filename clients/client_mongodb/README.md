# client_mongodb — the dashboard template

This folder is the **standard pattern every client dashboard follows**. To make a
new client, copy this folder and change one line (`CLIENT = "..."` in
`job/main.py`) and point its views at the right filter. Everything else — bucket
names, dataset, the JSON file — follows automatically.

If you only read one thing: **to refresh the live dashboard, run two commands** —
refresh the shared raw layer, then run this job (see [§ Deploy](#deploy-copy-paste)).

---

## How it works (the 3 stages)

```
 (1) SOURCE → BIGQUERY            (2) BIGQUERY → JSON             (3) JSON → FRONTEND
 ────────────────────            ──────────────────              ──────────────────
 snowflake_data_pull copies       Views filter THIS client's      A web app shows a login
 the Snowflake tables (ALL         slice out of the shared raw     page, then dashboard.html,
 clients, unfiltered) into         tables + roll them up, then     which fetches the JSON and
 shared raw_snowflake.*            the job reads the views and     draws all the charts.
                                   writes mongodb.json to GCS
        │                              │          │                        │
  ingest/snowflake_data_pull/           client_mongodb    job/main.py         dash/dashboard.html
  loader.py  (SHARED)             /sql/*.sql       (env={...} dict)    dash/main.py (login)
        │                         (the views)          │                    │
        └ shared Cloud job        └──── this client's Cloud Run JOB ────┘  └ Cloud Run SERVICE
          (raw, all clients)             "mongodb-export" (stages 2)          "mongodb-dash" (3)
```

Two things changed from the "obvious" design, and they matter:

1. **Stage 1 is shared and lives OUTSIDE this folder** — in `ingest/snowflake_data_pull/`.
   It does a dumb full copy of the Snowflake source tables into `raw_snowflake.*`
   **once for every client**. This job no longer touches Snowflake at all.
2. **The per-client filter lives in the views, not the pull.** This client's
   3 DNB campaign IDs and the country→market mapping are in `sql/02_stg_salesforce.sql`
   (and the advertiser filter in `sql/01_stg_tradedesk.sql`).

So this folder's **`job/main.py` is now just stage 2**: read BigQuery views → write
`mongodb.json`. Deployable things:

| Folder  | Cloud Run name   | Type                      | What it does |
|---------|------------------|---------------------------|--------------|
| `../snowflake_data_pull/` | (run manually for now) | shared loader | stage 1 → fills `raw_snowflake.*` for ALL clients |
| `job/`  | `mongodb-export` | **Job** (runs, then exits) | stage 2 → views → `mongodb.json` |
| `dash/` | `mongodb-dash`   | **Service** (always on)    | stage 3 → serves the dashboard |

The BigQuery **views** (`sql/`) are the stage-2 transform; apply them with
`python create_views.py`.

---

## What do I edit?

| I want to change…                                            | Edit this                                      | Stage |
|--------------------------------------------------------------|------------------------------------------------|:-----:|
| Pull a new Snowflake **source table** (for everyone)         | `../snowflake_data_pull/loader.py` (`TABLES`)  |   1   |
| This client's **filter** (campaign IDs, advertiser, leads)   | `sql/01_stg_tradedesk.sql` / `02_stg_salesforce.sql` | 2 |
| How data is grouped / bucketed (lead-status buckets, etc.)   | the relevant view in `sql/*.sql`               |   2   |
| The shape/keys of the JSON the frontend receives             | `job/main.py` → the `env = {...}` dict         |   2   |
| The charts, tabs, layout, colours                            | `dash/dashboard.html`                          |   3   |
| Login / how the JSON is served                               | `dash/main.py` (rarely needed)                 |   3   |

---

## The "contracts" (what breaks if you rename something)

Each stage passes data to the next **by name**:

1. **Snowflake columns → the views** — `sql/01_stg_tradedesk.sql` / `02_stg_salesforce.sql`
   read raw columns by name (`AD_TYPE`, `CAMPAIGN_ID`, …). The raw tables are a
   `SELECT *` mirror, so a Snowflake rename surfaces here.
2. **View columns → `job/main.py`** — `main()` reads them like `r["TOTAL_LEADS"]`. Rename a view column → fix `main.py`.
3. **JSON keys → `dashboard.html`** — the page reads `data.cs[i].total`, `data.rows[i].spend_usd`, etc. Change a key in `env={...}` → fix `dashboard.html`.

---

## Deploy (copy-paste)

PowerShell. Project `bidbrain-analytics`, region `australia-southeast1`. Use the
repo `.venv` for the Python scripts (`.\.venv\Scripts\python.exe`). **All deploys
are manual — there are no auto-deploy triggers.**

> ⚠️ Don't use `gcloud builds submit --config cloudbuild.yaml` from your laptop.
> Its deploy step fails (`PERMISSION_DENIED: iam.serviceaccounts.actAs`) because
> Cloud Build's own account can't act as the runtime service account. Those
> `cloudbuild.yaml` files are for a future push-to-main trigger that isn't set up
> yet. For now: **build the image, then deploy as yourself** (below).

**① Refresh the data** — normally **automatic**. `mongodb-export` is **self-gating** on a Cloud
Scheduler `*/10 * * * *` UTC tick (`../scheduler.ps1`): each tick cheaply probes whether the
`raw_snowflake` tables its views read advanced (via `__TABLES__.last_modified`) and rebuilds only
when they did, so the dashboard refreshes within ~10 min of new upstream data. To force a refresh
by hand — two steps: refresh the shared raw layer, then run the job:
```powershell
.\.venv\Scripts\python.exe snowflake_data_pull\loader.py        # stage 1: Snowflake -> raw_snowflake (all clients)
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait   # stage 2: views -> mongodb.json
```
*(If `raw_snowflake` is already fresh, the second command alone refreshes this client. The gate
still applies on a manual `execute`; set `FORCE_REBUILD=1` to bypass it.)*

**② You edited a view (`sql/*.sql`)** — apply views, then re-run the job:
```powershell
.\.venv\Scripts\python.exe client_mongodb\create_views.py
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

**③ You edited `job/main.py`** (the JSON shape) — build, swap, run:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_mongodb/job --tag $IMG --region australia-southeast1
gcloud run jobs update  mongodb-export --image $IMG --region australia-southeast1
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

**④ You edited `dash/dashboard.html` or `dash/main.py`** — build + redeploy the service:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_mongodb/dash --tag $IMG --region australia-southeast1
gcloud run services update mongodb-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready — no "run" step. It
reads whatever JSON is currently in the bucket.

---

## What each part needs (for when something breaks)

- **Stage 1** (`snowflake_data_pull`): the Snowflake key secret `snowflake-bq-key`
  (via `$SNOWFLAKE_KEY` or Secret Manager), and write access to `raw_snowflake`.
- **Job** (stage 2): runtime SA `mongodb-dash-job@…` with BigQuery write on
  `client_mongodb` **and read on `raw_snowflake`** (the views read across to it),
  Storage write on the bucket, and the views existing. It does **not** touch
  Snowflake anymore.
- **Views** (stage 2): `raw_snowflake.*` must be populated (stage 1), and views
  applied in order (`stg_*` → `paid_media_model` → `cs_leads` / rollups — the
  `NN_` filename prefix enforces this).
- **Service** (stage 3): `mongodb.json` in the bucket, secrets
  `mongodb-dash-password` + `mongodb-dash-session-key`, runtime SA
  `mongodb-dash-web@…` (Storage read + Secret access). Org policy blocks public
  access, so the service runs with `--no-invoker-iam-check` and does its own
  password gate.

## Coordinates

| | |
|---|---|
| GCP project | `bidbrain-analytics` |
| Region | `australia-southeast1` |
| Artifact Registry repo | `bidbrain` |
| Shared raw dataset | `raw_snowflake` (filled by `../snowflake_data_pull/`) |
| Job | `mongodb-export` |
| Service | `mongodb-dash` → https://mongodb-dash-p32gk2wuia-ts.a.run.app |
| Data bucket / file | `bidbrain-analytics-mongodb-dash` / `mongodb.json` |

## Subfolder guides (read these for detail)

- [`job/`](job/README.md) — the export job (stage 2): reads BigQuery views → writes `mongodb.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + serves the dashboard UI.
- [`sql/`](sql/README.md) — the BigQuery view DDL (the stage-2 transform) + how to apply / re-export it.

## Files in this folder

| Path | What it is |
|---|---|
| `job/main.py` | The export job — freshness gate, then reads BigQuery views and writes `mongodb.json` (stage 2). No Snowflake. |
| `job/freshness.py` | Vendored self-gating helper (BQ `__TABLES__` probe + `_freshness.json` GCS watermark). |
| `job/cloudbuild.yaml`, `job/Dockerfile` | How the job is built/deployed (used by a future trigger) |
| `scheduler.ps1` | Creates/refreshes the Cloud Scheduler `*/10` UTC trigger that runs the self-gating `mongodb-export` job. |
| `sql/*.sql` | BigQuery view definitions (the stage-2 transform); `01/02_stg_*` hold this client's filter |
| `create_views.py` | Applies every `sql/*.sql` view to BigQuery |
| `dash/main.py` | The web app — login + serves `dashboard.html` and the JSON (stage 3) |
| `dash/dashboard.html` | The actual dashboard UI (all charts/tabs live here) |
| `dash/cloudbuild.yaml`, `dash/Dockerfile` | How the service is built/deployed |

> Stage 1 (the Snowflake → `raw_snowflake` copy) lives in `../snowflake_data_pull/`
> because it's shared by every client, not specific to MongoDB.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — stage 1 (fills `raw_snowflake`, shared).
- [`../client_cloudflare/`](../client_cloudflare/README.md) — the second client, and how/why it diverges from this template.
