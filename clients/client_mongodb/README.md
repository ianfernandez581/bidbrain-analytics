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
| **Lead targets / media-plan budget**                         | `targets/targets.csv` · `targets/budget.csv` → `seed_static.py` → export `FORCE_REBUILD=1` | 2 |
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
| `sql/*.sql` | BigQuery view definitions (the stage-2 transform); `01/02_stg_*` hold this client's filter; `11_stg_tradedesk_pixel`→`12_pixel_assets`/`13_pixel_summary` are the content-engagement views (LIVE from `raw_snowflake.tradedesk_apac_conversion`) |
| `create_views.py` | Applies every `sql/*.sql` view to BigQuery |
| `dash/main.py` | The web app — login + serves `dashboard.html` and the JSON (stage 3) |
| `dash/dashboard.html` | The actual dashboard UI (all charts/tabs live here) |
| `dash/cloudbuild.yaml`, `dash/Dockerfile` | How the service is built/deployed |

> Stage 1 (the Snowflake → `raw_snowflake` copy) lives in `../snowflake_data_pull/`
> because it's shared by every client, not specific to MongoDB.

## Content engagement (Trade Desk Universal Pixel) — LIVE from Snowflake

The Paid Media tab carries a **Content engagement** section, now sourced **live** from
`raw_snowflake.tradedesk_apac_conversion` (the per-fire TTD Universal Pixel feed, mirrored by
[`snowflake_data_pull`](../../ingest/snowflake_data_pull/README.md)) via `stg_tradedesk_pixel`
→ `pixel_assets` / `pixel_summary`. It refreshes on the normal `*/10` cadence — **no manual CSV
step** (the old `seed_pixel.py` + seed tables were retired). MongoDB's slice is
`ADVERTISER_ID = '9c1w83i'` (the conversion table has no `ADVERTISER_NAME`).

What the numbers mean:
- **Content LP views** = the named `MDB_UPM_LPView_*` pixels (real content engagement). Under
  **DNB**, **Gartner MQ Leader dominates (~30× any other asset)**; the content pixels are almost
  entirely click-driven (click vs view-through is derived: `DISPLAY_CLICK_COUNT > 0`).
- **Ad-influenced site visits** = the catch-all `Default` Universal Pixel, ~95% **view-through**
  (saw an ad, later reached mongodb.com). It's a reach/influence signal — **label it as such, not
  hard leads** (the dashboard does, in `#pxNote`).
- **Driven by the DNB / KGA(IDC) campaign toggle** (the same toggle as the rest of the Paid Media
  tab), but **independent of the region & date filters**. Each fire's campaign is derived from its
  attributed campaign name — `COALESCE(FIRST_DISPLAY_CLICK_CAMPAIGN_NAME,
  FIRST_IMPRESSION_CAMPAIGN_NAME)` → `SPLIT("_")[2]` → `campaignOf` (IDE/DNB → DNB, else IDC) — so
  100% of fires are attributed (zero unattributed). **KGA(IDC) is legitimately sparse** (~122
  content LP views vs DNB's ~4,085) — the section renders the real numbers, it does not hide them.
- The old **Device / Ad-Environment / Creative-size** dimension charts are **gone** — those cuts
  aren't in the conversion feed.

It rebuilds automatically when new conversions land (the export job's freshness gate watches
`raw_snowflake.tradedesk_apac_conversion`). For an immediate rebuild after a view edit, force it:
`gcloud run jobs execute mongodb-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait`.

> **History note:** the conversion feed starts **2026-06-01**, whereas the retired CSV seed
> covered from May 19 — so the section no longer shows May 19–31; it went live 2026-06-17.

## Margin multiplier ("spent in full")

A **frontend-only** gross-up that reports paid media on the **client-billed basis** so the
campaign shows as *spent in full*. All logic lives in `dash/dashboard.html` (search `MARGIN`) —
**the `mongodb.json` in the bucket keeps RAW spend**, so the status-dashboard accuracy checks
(JSON vs Snowflake) are unaffected and nothing in the pipeline changed.

- **Multiplier is per campaign** (DNB / KGA-IDC), constant across the whole flight. Two modes,
  chosen in the **Margin** control (a calculator popover next to the Date-range picker):
  - **Spent in full** (default, `mode:'auto'`): multiplier = `gross budget ÷ actual spend`, so
    grossed spend lands exactly on the gross budget (Calvin's MongoDB example ≈ **×1.23**).
  - **Client margin** (`mode:'margin'`): the reusable calculator `marginToMultiplier(pct)` =
    `1 / (1 − margin)` — a client inputs their margin %, and that drives the multiplier
    (18.75 % ⇒ ×1.23). This is the per-client capability meant to generalise across dashboards.
- **What's scaled:** each row's `spend_usd` is grossed once at load (stashing `_rawSpend`, so it's
  idempotent), which propagates to every spend total, **CPM, CPC** and the charts/tables/CSV/AI-deck
  automatically. The plan **CPM/CPC benchmarks + est-CPC are grossed by the same factor**, so the
  vs-plan deltas stay true. **Not scaled:** impressions/clicks/leads (counts), the **gross/net budget
  anchors**, and **content-syndication lead economics** (plan CPL / committed CS spend — a separate
  budget line; flip `MARGIN.scaleCS:true` to include it).
- **Turn off** in the popover to revert to raw media cost. A "Margin-adjusted ×N · Spent in full"
  pill shows on the Paid Media tab whenever it's active, so the adjustment is never hidden.
- Redeploy is the standard dashboard-only path: `dash/deploy_dash_mongodb.ps1` (no job/SQL change).

> **Follow-up (not built here):** a *platform-wide* per-client margin store — where each client
> inputs their margin into BidBrain once and every dashboard reads it — belongs in
> `bidbrain-platform/` (the admin/registry), not in each dashboard. This MongoDB build is the
> working reference: the same `marginToMultiplier()` formula + per-campaign auto fallback.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — stage 1 (fills `raw_snowflake`, shared).
- [`../client_cloudflare/`](../client_cloudflare/README.md) — the second client, and how/why it diverges from this template.
