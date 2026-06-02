# client_mongodb — the dashboard template

This folder is the **standard pattern every client dashboard follows**. To make a
new client, copy this folder and change one line (`CLIENT = "..."` in
`job/main.py`). Everything else — bucket names, dataset, the JSON file — follows
automatically.

If you only read one thing: **to refresh the live dashboard data, run the job**
(command in [§ Deploy](#deploy-copy-paste)). That's it.

---

## How it works (the 3 stages)

```
 (1) SOURCE → BIGQUERY        (2) BIGQUERY → JSON            (3) JSON → FRONTEND
 ───────────────────         ──────────────────             ──────────────────
 Pull from Snowflake          Views reshape the raw          A web app shows a login
 (Salesforce + TradeDesk),    src_* tables, then the job     page, then dashboard.html,
 load RAW into BigQuery       reads them and writes          which fetches the JSON and
 tables src_salesforce /      mongodb.json into a            draws all the charts.
 src_tradedesk                private GCS bucket
        │                          │         │                       │
   job/main.py                sql/*.sql   job/main.py            dash/dashboard.html
   (SF_SQL / TD_SQL)          (the views) (the env={...} dict)   dash/main.py (login)

        └────── one Cloud Run JOB: "mongodb-export" ──────┘     └ one Cloud Run SERVICE:
                (stages 1 AND 2 are the same program)             "mongodb-dash" (stage 3)
```

The thing that trips people up: **stages 1 and 2 are the same program.**
`job/main.py` pulls from Snowflake *and* writes the JSON in a single run. The
BigQuery **views** (`sql/`) are the "reshape" step in the middle — they're not on
Cloud Run; you apply them with `python create_views.py`.

So there are **two deployable things**:

| Folder  | Cloud Run name   | Type                      | What it does |
|---------|------------------|---------------------------|--------------|
| `job/`  | `mongodb-export` | **Job** (runs, then exits) | stages 1 + 2 → writes `mongodb.json` |
| `dash/` | `mongodb-dash`   | **Service** (always on)    | stage 3 → serves the dashboard |

---

## What do I edit?

| I want to change…                                            | Edit this                                  | Stage |
|--------------------------------------------------------------|--------------------------------------------|:-----:|
| What's pulled from Snowflake (a filter, a column, campaigns) | `job/main.py` → `SF_SQL` / `TD_SQL`        |   1   |
| How data is grouped / bucketed (e.g. lead-status buckets)    | a view in `sql/*.sql`                      |   2   |
| The shape/keys of the JSON the frontend receives             | `job/main.py` → the `env = {...}` dict     |   2   |
| The charts, tabs, layout, colours                            | `dash/dashboard.html`                      |   3   |
| Login / how the JSON is served                               | `dash/main.py` (rarely needed)             |   3   |

---

## The 3 "contracts" (what breaks if you rename something)

Each stage passes data to the next **by name**. Rename on one side → update the other:

1. **Snowflake columns → `SF_SQL`/`TD_SQL`** — the SELECT must use real column names.
2. **View columns → `job/main.py`** — `main()` reads them like `r["TOTAL_LEADS"]`. Rename a view column → fix `main.py`.
3. **JSON keys → `dashboard.html`** — the page reads `data.cs[i].total`, `data.rows[i].spend_usd`, etc. Change a key in `env={...}` → fix `dashboard.html`.

---

## Deploy (copy-paste)

PowerShell. Project `bidbrain-analytics`, region `australia-southeast1`. **All
deploys are manual — there are no auto-deploy triggers.**

> ⚠️ Don't use `gcloud builds submit --config cloudbuild.yaml` from your laptop.
> Its deploy step fails (`PERMISSION_DENIED: iam.serviceaccounts.actAs`) because
> Cloud Build's own account can't act as the runtime service account. Those
> `cloudbuild.yaml` files are for a future push-to-main trigger that isn't set up
> yet. For now: **build the image, then deploy as yourself** (below).

**① Just refresh the data** (no code change) — run the job, done:
```powershell
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

**② You edited `job/main.py`** (a query, or the JSON shape) — build, swap, run:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-export:$(git rev-parse --short HEAD)"
gcloud builds submit client_mongodb/job --tag $IMG --region australia-southeast1
gcloud run jobs update  mongodb-export --image $IMG --region australia-southeast1
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```

**③ You edited a view (`sql/*.sql`)** — apply views, then re-run the job:
```powershell
python client_mongodb/create_views.py
gcloud run jobs execute mongodb-export --region australia-southeast1 --wait
```
> Heads-up: the live view SQL isn't all in `sql/` yet — some views exist only
> inside BigQuery. To edit one today, change it in the BigQuery console, or
> export it to `sql/NN_<view>.sql` first (see `sql/README.md`). The `NN_` number
> prefix sets the apply order (`stg_*` views before the models that read them).

**④ You edited `dash/dashboard.html` or `dash/main.py`** — build + redeploy the service:
```powershell
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/mongodb-dash:$(git rev-parse --short HEAD)"
gcloud builds submit client_mongodb/dash --tag $IMG --region australia-southeast1
gcloud run services update mongodb-dash --image $IMG --region australia-southeast1
```
The service goes live as soon as the new revision is ready — no "run" step. It
reads whatever JSON is currently in the bucket.

---

## What each part needs (for when something breaks)

- **Job** (stages 1+2): the Snowflake key secret `snowflake-bq-key`, runtime SA
  `mongodb-dash-job@…` (BigQuery write + Secret access), the `client_mongodb`
  dataset, and the views (it reads them).
- **Views** (stage 2): the `src_*` tables must exist first, applied in order
  (`stg_*` → `paid_media_model` → `cs_leads` / rollups).
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
| Job | `mongodb-export` |
| Service | `mongodb-dash` → https://mongodb-dash-p32gk2wuia-ts.a.run.app |
| Data bucket / file | `bidbrain-analytics-mongodb-dash` / `mongodb.json` |

## Files in this folder

| Path | What it is |
|---|---|
| `job/main.py` | The export job — pulls Snowflake → BigQuery, then writes `mongodb.json` (stages 1 + 2) |
| `job/cloudbuild.yaml`, `job/Dockerfile` | How the job is built/deployed (used by a future trigger) |
| `sql/` | BigQuery view definitions (the stage-2 transform) + how to export them |
| `create_views.py` | Applies every `sql/*.sql` view to BigQuery |
| `dash/main.py` | The web app — login + serves `dashboard.html` and the JSON (stage 3) |
| `dash/dashboard.html` | The actual dashboard UI (all charts/tabs live here) |
| `dash/cloudbuild.yaml`, `dash/Dockerfile` | How the service is built/deployed |
