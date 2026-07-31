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

## LinkedIn lane (paid social) — from Windsor, NOT Snowflake/TTD

New in **2026-07**: MongoDB's **AWS Immersion Day** lead-gen campaign
(`MONGODB_2026-Q3_AWS-IMMERSION-DAY_AU_LEAD-GENERATION_LINKEDIN`) runs on **LinkedIn**, not Trade
Desk, so it's a separate lane sourced from the shared Windsor raw layer:

- **Data:** `raw_windsor.perf_linkedin` (built by [`ingest/windsor_data_pull/linkedin`](../../ingest/windsor_data_pull/linkedin/README.md)) → views `sql/14_stg_linkedin` → `15_linkedin_summary` / `16_linkedin_daily` / `17_linkedin_by_campaign`. Scope = `campaign_name LIKE 'MONGODB%'` (picks up this campaign + any future MongoDB LinkedIn campaign). Spend is FX'd to **USD** (LinkedIn is native AUD; AUD×0.65), so it sits on the same currency as the rest of the dashboard.
- **Job:** `job/main.py` emits a `linkedin` block **only when there's real delivery** (`imps > 0`); otherwise it's `null`. `raw_windsor.perf_linkedin` is added to `GATING_TABLES` so a LinkedIn refresh triggers a rebuild.
- **Dashboard:** a **LinkedIn tab** in `dash/dashboard.html` (`renderLinkedInAll`) — KPIs (spend / imps / clicks / leads with CPM/CTR/CPL), a tri-axis daily chart (reusing the VIEW BY / AXIS toggles + the date-range picker), a lead-gen funnel, and a by-campaign table. The tab **auto-hides** until `DATA.linkedin` has delivery (like Schneider's GA4 tab). LinkedIn spend grosses by `bbMultFor('linkedin')`.

> **⚠️ Blocked until a Windsor re-auth.** The campaign is live and delivering in LinkedIn, but its ad
> account (**`502299829`**) returns a hard **HTTP 500 `'start'`** on every Windsor request — a
> Windsor-side bug where a campaign missing a start date crashes the account's whole adAnalytics
> pull. The loader skips that account, so `perf_linkedin` has **no MongoDB rows yet** and the tab
> stays hidden. **Fix:** re-authorize/re-sync the LinkedIn connector for that account in Windsor
> (the `'start'` bug usually clears on reconnect), or archive/fix the start-date-less campaign in
> LinkedIn Campaign Manager. Once readable, `windsor-linkedin-ingest` (daily 21:40 UTC) loads it and
> the tab lights up automatically — no code change. Verified 2026-07-21; see the ingest README.

## DNB spend adjustment (one-time, hardcoded)

The **DNB** campaign under-delivered its budget — raw media cost ≈ **$16,183.91** vs the
client-billed budget — and a reported spend *below* budget is bad for our business model. So
DNB's reported paid spend is **grossed up to a fixed target ($19,890)**. A **frontend-only**
adjustment in `dash/dashboard.html` (search `MARGIN_TARGET`); **the `mongodb.json` in the bucket
keeps RAW spend**, so the status-dashboard accuracy checks (JSON vs Snowflake) are unaffected.

- **DNB only, one-off, hardcoded.** `const MARGIN_TARGET = { DNB: 19890 };` (campaign key →
  reported paid spend, USD). KGA (IDC) is **not** in the map, so it stays on raw spend (×1).
- **Multiplier = target ÷ raw whole-flight spend** (≈ **×1.229**), so DNB's displayed spend lands
  exactly on the target. Each row's `spend_usd` is grossed once at load (stashing `_rawSpend`, so
  it's idempotent), which propagates to every spend total, **CPM, CPC** and the charts/tables/CSV/
  AI-deck automatically. The plan **CPM/CPC benchmarks + est-CPC are grossed by the same factor**,
  so vs-plan deltas stay true. **Not scaled:** impressions/clicks/leads (counts), the gross/net
  budget anchors, and content-syndication lead economics (plan CPL / committed CS spend).
- **HIDDEN FROM THE CLIENT — no control, no label.** There is no UI at all; the grossed numbers
  simply read as the real spend. The AI slide deck shows the grossed figures but its payload
  (`buildReportPayload`) deliberately omits any mention of the adjustment.
- **To change the figure:** edit `MARGIN_TARGET`. **To remove the adjustment entirely:** set it to
  `{}`. Redeploy is the standard dashboard-only path: `dash/deploy_dash_mongodb.ps1` (no job/SQL change).

## CS weekly pacing — real lead dates, not a ramp (fixed 2026-07-31)

The Content Syndication **"Weekly pacing - target vs actual"** chart shows **true per-week lead
counts**. It did not always: until 2026-07-31 `buildWeekly()` had no dates to work with and spread
the whole-flight lead total evenly across the elapsed window
(`p.leads * days / p.elapsed`). That drew an identical bar every week regardless of real delivery -
KGA/IDC read a flat 63 leads/week right through July even though its last lead landed **2026-07-02**,
which is what surfaced the bug ("why are leads arriving after the campaign ended?").

- **Source:** `sql/18_cs_daily.sql` → `cs_daily` → job key `cs_daily` → `buildWeekly()`. Salesforce
  leads have always carried a populated `DAY` (0 NULLs); view `05` just aggregated it away.
- **Reconciliation:** `cs_daily` uses the SAME two delivered-lead definitions as `05`, so the bars
  sum exactly to the headline Total/Delivered (verified: DNB 413, KGA/IDC 615). **Change one, change
  both** or the chart stops matching the KPI above it.
- **Axis = the plan window UNION the weeks that actually carry leads.** KGA/IDC delivered 283 leads
  (46% of its total) before its seeded plan start of 05-25, and DNB's first lead predates its 04-01
  start by a day; a plan-window-only axis would silently drop them. Weeks past the last lead render
  a real **0**, which is how under-delivery reads honestly. The target pace is still spread across
  the **plan** weeks only (null outside them).
- **KGA/IDC's flight end was moved 2026-07-31 → 2026-07-05** (client call, 2026-07-31) in
  `targets/budget.csv` → `seed_budget` → `sql/10_budget` → job `budget` → `campaignWindow()`. The
  original 07-31 was the signed media-plan end, but delivery under the original TTD campaign names
  stopped 07-05, so the chart carried four empty trailing weeks. At 07-05 the axis ends on the week
  of 06-29 (which closes Sun 07-05), the weekly target re-spreads to 609 ÷ 6 = **102/week**, and the
  pacing card reads **Day 42 of 42**. `campaignWindow()` feeds `csPacing()` ONLY, so this moves the
  CS pacing card and the weekly chart together and touches nothing on the Paid Media tab.
  **Caveat:** paid delivery did NOT actually stop on 07-05 - it ran to 07-30 under campaign names
  that gained a `2265_` brief prefix (see the parsing gotcha below), so 07-05 is the end of
  *visible* delivery. Revisit this date if that parse is fixed.
- **Do not edit the media-plan dates to make a chart look tidy.** Shortening a window to hide empty
  weeks hides under-delivery. This change was the opposite case: the plan end was later than the
  campaign's real (visible) delivery end, so the empty weeks were an artefact, not a finding.
- **The date-range picker is still greyed on the CS / Compare tabs.** The KPIs and the market /
  programme splits still read the whole-flight `cs_by_programme`, which has no date grain. `cs_daily`
  carries the full accepted/rejected/new breakdown at day grain specifically so a future date-scoped
  CS view needs no new view - but scoping those aggregates would also change the numbers the
  status-dash accuracy check reconciles against, so it is a deliberate follow-up, not a side effect.

## OPEN DEFECT — the `2265_` campaign-name prefix breaks positional parsing (found 2026-07-31)

**Not yet fixed.** [`sql/01_stg_tradedesk.sql`](sql/01_stg_tradedesk.sql) parses the TTD campaign
name by FIXED offset (`SPLIT(CAMPAIGN_NAME,"_")[SAFE_OFFSET(2)]` etc). On **2026-07-06** the campaign
names gained a `2265_` brief-number prefix, which shifts every field one slot:

    old:  MONGODB_2026-Q2_IDC_APJ_DEMAND-GENERATION_ANZ        (to 2026-07-05)
    new:  2265_MONGODB_2026-Q2_IDC_APJ_DEMAND-GENERATION_ANZ   (from 2026-07-06)

| Field | Should be | Parses as |
|---|---|---|
| `PROGRAMME` | `IDC` / `IDE` | `2026-Q2` |
| `MARKET` | `ANZ` / `ASEAN` / `INDIA` / `KR-HK-TW` | `DEMAND-GENERATION` |
| `OBJECTIVE` | `DEMAND-GENERATION` | `APJ` |

`STRATEGY` still parses correctly - **`AD_GROUP_NAME` was NOT renamed**, which is why nothing looked
broken. `DEMAND-GENERATION` is not one of the five market chips and every paid row is gated on
`marketOk(r.market)` ([`dash/dashboard.html`](dash/dashboard.html) line ~1415, plus the CSV export and
the AI-deck payload), so **2,949 rows / US$11,670.55 of spend dated 2026-07-06 → 07-30 are silently
dropped from the dashboard** - about 25% of MongoDB's total TTD spend. All of it belongs to IDC (the
`2265_*_IDE_*` campaigns carry $0), so KGA/IDC's true spend is ~$29,726 against its $37,200 gross
budget while the dash shows $18,056. The DNB `MARGIN_TARGET` gross-up is unaffected.

**Fix when actioned:** index from the END of the name instead of the start - the market is always the
last token and the programme always fourth-from-last in BOTH formats, so
`ARRAY_REVERSE(SPLIT(CAMPAIGN_NAME,"_"))[SAFE_OFFSET(0)]` / `[SAFE_OFFSET(3)]` parse old and new
correctly and survive the next prefix. Then `sql/deploy_views_mongodb.ps1` (reapplies + force-runs).
Same rollout that hit **schneiderlqai** (`2306_` prefix, same date) - that client dodged it by keying
on `LIKE '%LQAIDC%'` instead of positional splits.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — stage 1 (fills `raw_snowflake`, shared).
- [`../client_cloudflare/`](../client_cloudflare/README.md) — the second client, and how/why it diverges from this template.
