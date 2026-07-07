# client_cloudflare — Cloudflare APAC dashboard on the MongoDB GCP pattern

**Status: LIVE.** The gated web app is deployed and serving (HTTP 200 verified
2026-06-04). See [`dash/LIVE_URL.md`](dash/LIVE_URL.md) for the URL.

This folder runs the **Cloudflare** dashboard on the same Google Cloud
architecture as `client_mongodb` — **BigQuery owns the model** (since 2026-06-17;
see [BigQuery owns the model](#bigquery-owns-the-model-was-the-snowflake-modelled-exception)):

```
raw_snowflake.* mirrors (shared ingest/snowflake_data_pull)  +  client_cloudflare.seed_* (static, from data/)
  -> BigQuery views (clients/client_cloudflare/sql)      staging -> models
  -> Cloud Run JOB  (clients/client_cloudflare/job)      read views -> cloudflare.json   (NO Snowflake)
  -> GCS (private)  gs://bidbrain-analytics-cloudflare-dash/cloudflare.json
  -> Cloud Run SERVICE (clients/client_cloudflare/dash)  password gate + serves dashboard.html + proxies /data.json
  -> Platform front-door  https://dashboards.bidbrain.ai/d/cloudflare/  (reverse-proxies + one login)
```

The `cloudbuild.yaml` files are a **future** push-to-main CD trigger (one per
unit, like MongoDB §11) — **not active**. This client was stood up, and is
redeployed, by the manual order below.

This replaces Cloudflare's current setup (Snowflake **tasks** writing
`pacing.json` + `paid_media.json` to a **public** R2 bucket, read by a static
page). The two payloads are merged into one `cloudflare.json`, served behind the
same Flask password gate MongoDB uses.

## What's in this folder

| Path | What it is |
|---|---|
| [`job/`](job/README.md) | **Export Job** (`cloudflare-export`): reads the BigQuery views → writes `cloudflare.json`. **No Snowflake** (BQ-only, like MongoDB). [Guide →](job/README.md) |
| [`dash/`](dash/README.md) | **Web App** (`cloudflare-dash`): password gate + serves `dashboard.html` + proxies `/data.json`. [Guide →](dash/README.md) |
| [`sql/`](sql/README.md) | The BigQuery **model** views — staging (`stg_*`) → `paid_media_model`/`pacing_model`/etc. — over `raw_snowflake.*` + the `seed_*` static tables. [Guide →](sql/README.md) |
| [`create_views.py`](create_views.py) | Applies every `sql/*.sql` view (runner; `NN_` prefix = dependency order). |
| `data/` | Local CSV snapshots of the three STATIC Snowflake tables (pacing targets, account tiers, LINE JP). **Gitignored** (`clients/*/data/`) — `TIERS` is sensitive client ABM data — so it's NOT in the repo; regenerate with `pull_static.py`. The live seeds persist in BigQuery (`seed_*`). |
| [`pull_static.py`](pull_static.py) | **One-time** Snowflake → `data/*.csv` pull (manual; needs the Snowflake key; re-run on a fresh checkout or when a static upload changes). **⚠️ The Q2 pacing targets in `seed_real_targets` were rebalanced on 2026-06-19 directly in BQ + `data/real_targets.csv` (grand total unchanged at 3216; regional split updated to the client's new Phase×Region table — see git log). The Snowflake `CLOUDFLARE_SANDBOX.CS_REPORTING.REAL_TARGETS` source was NOT updated, so re-running `pull_static.py` will REVERT this. Update Snowflake first, or skip the real_targets pull.** |
| [`seed_static.py`](seed_static.py) | Loads `data/*.csv` → BigQuery `client_cloudflare.seed_*` (no Snowflake). Re-run after `pull_static.py`. |
| [`snowflake_v_*.sql`](snowflake_v_salesforce_leads_live.sql) | **Reference only** now — the live Snowflake DDL for Cloudflare's OWN legacy R2 export tasks. NOT part of this pipeline (the BQ `sql/` views are the source of truth). |
| [`scheduler.ps1`](scheduler.ps1) | Creates/refreshes the Cloud Scheduler trigger for `cloudflare-export` (default `*/10` UTC; pass `-Cron` to override). The job self-gates, so most ticks no-op. Idempotent. |

> There is **no** one-shot `deploy_cloudflare.ps1` for this client — it was stood
> up via the manual order in [One-time replicate / deploy order](#one-time-replicate--deploy-order)
> below. (Only STT has a one-shot stand-up script, `clients/client_STT/deploy_stt.ps1`.)

## BigQuery owns the model (was the Snowflake-modelled exception)

Until 2026-06-17 Cloudflare was the **only** client that didn't follow the repo
pattern: the job pulled Snowflake's pre-modelled `CLOUDFLARE_SANDBOX.*` views and
landed them as thin `src_*` pass-throughs. It's now on the standard MongoDB pattern —
**BigQuery owns the model**:

- The four **dynamic** platform tables are already mirrored into `raw_snowflake`
  by the shared `ingest/snowflake_data_pull` unit (no Cloudflare-specific pull).
- The **static** Cloudflare-only tables (`REAL_TARGETS`, `TIERS`, the LINE JP upload)
  were pulled once to [`data/`](data/) (`pull_static.py`) and seeded into BigQuery
  `seed_*` (`seed_static.py`). **LINE no longer comes from Snowflake** — see
  [Updating LINE (manual)](#updating-line-manual) below.
- The Snowflake modelling SQL was **ported into [`sql/`](sql/README.md)** — the
  `V_STG_*` staging, `V_PAID_ADS_FINAL_MODEL`, `V_SALESFORCE_LEADS_LIVE`,
  `V_TIER_MAPPING_CLEANED`, `V_TARGETS_V2_NORM`, `V_PACING_FINAL_MODEL`, and the
  hardcoded benchmark/`li_weekly` constants — over `raw_snowflake.*` + the seeds.
- The job no longer touches Snowflake; it just reads the views (gates on BQ
  `__TABLES__.last_modified` like every other client).

**Verified parity** on the cutover: every headline figure matches the old pipeline
exactly (paid media per-channel imps/clicks/spend, creatives, 12 CS campaigns,
3911 leads / 3328 accepted / 416 rejected / 167 new, the 3 LinkedIn campaign dashes).
The pacing **tier** sub-split (Tier 2/3/Other) is **non-deterministic in the source
model** — `TIERS` has 742 cleaned account names mapping to conflicting tiers and 349
accepted leads match multiple tiers, so the post-join `QUALIFY` dedup picks a tier
arbitrarily. The old Snowflake view re-resolves these on every rebuild too; the BQ
port reproduces the model faithfully, so that split flickers as it always did (the
region totals and all headline counts are stable/exact).

### Updating LINE (manual)

LINE is the **one channel with no API/Windsor connector** — it's a hand-download from
LINE Ad Manager. The old Snowflake relay (`V_STG_LINE_CF` → `pull_static.py`) is being
**retired**: the LINE Ads account is migrating to **LY Ads** (LINE×Yahoo merger; LINE
Ads delivery ends ~late Oct 2026), and pre-migration the old account view gates behind
the migration tool. So LINE now flows **download → `data/line_cf.csv` directly**, no
Snowflake. Steps:

1. **Download** at https://admanager.line.biz/ → open the Cloudflare JP ad account →
   **☰ menu → Reports & Measurement → Performance report → + Create report**. Set
   **Aggregation interval = Daily (日別)**, level = **Ad**, format **CSV**, period =
   the full flight (or All time). The report generates async → download from the
   report list. (The dashboard's **Download report** button only emits a *Total*
   summary — it does NOT give daily rows; you need the Performance report builder.)
2. **Convert**: `.\.venv\Scripts\python.exe clients\client_cloudflare\convert_line_export.py`
   — auto-picks the newest `LINE*.csv` in `~/Downloads`, maps `Day/Ad name/Impressions/
   Clicks/Cost` → the `seed_line_cf` 7 cols (video cols → 0; these are IMAGE ads),
   sums to one row per (day, ad), and writes `data/line_cf.csv`. It prints range +
   totals — clicks should match the LINE UI exactly.
3. **Load + rebuild**: `seed_static.py` then the export job with `FORCE_REBUILD=1`
   (a seed change is invisible to the freshness gate). The model (`05_paid_media_model`
   `line_jp`) sums by day and converts **JPY→USD@155**.

### Updating targets (committed CSV → BQ)

CS pacing targets live in the **version-controlled** `targets/real_targets.csv` (week × tier ×
region × country × target) — NOT the gitignored `data/`. This is the per-client "targets in BQ from
a committed CSV" standard: the CSV is the source of truth, `seed_static.py` loads it into
`client_cloudflare.seed_real_targets`, and `sql/12_targets_v2_norm.sql` maps `(REGION, COUNTRY)` to
the 11 market codes. To change targets:

1. Edit `targets/real_targets.csv` (commit it).
2. `.\.venv\Scripts\python.exe clients\client_cloudflare\seed_static.py` (reloads `seed_real_targets`).
3. Run the export job with `FORCE_REBUILD=1` (a seed change is invisible to the freshness gate).

The per-market Q2 totals reconcile to the Q2 media-plan sheet (total **3216**). `tiers.csv`
and `line_cf.csv` stay in gitignored `data/` — they are pulled/manual snapshots, not targets.

**Q3 FY26 targets (added 2026-07-07).** Q3 rows appended for the 14 week-start Mondays
`2026-06-29 → 2026-09-28` (grand total now 3468; Q2 rows untouched). The client's Q3 file
(`targets/real_targets Q3.xlsx`) is a paid-media **activation plan**, NOT a weekly × tier CS
pacing table like the Q2 Snowflake source — so Q3 was built from the plan's **LinkedIn per-region
Commit Leads (252)**: ANZ 60 → AU 54 / NZ 6 (split by the Q2 90/10 ratio), ASEAN 80 → SIM 48 /
RoA 32 (plan's stated 60/40), SAARC 59, GCR-HK 11, JP 42; GCR-CN/GCR-TW/KR/RIG = 0 (RIG folded
into ANZ LinkedIn in Q3). **Single tier** (`Tier 2`) — the plan has no Tier 2/Tier 3 split —
and each quarter total spread **evenly across the 14 weeks** (largest-remainder integer split).
The dashboard's active quarter was rolled Q2→Q3 (default range = full Q3, all "Q2" labels → "Q3";
`Q3_START`/`Q3_END` in `dash/dashboard.html`). **Note:** 252 is much smaller than Q2's 3216
because it's the LinkedIn commit-lead plan, not CS 2-touch-MQL volume — reconfirm with the client
if a CS-MQL target is wanted instead (the plan only carries that at APAC+JP aggregate, no market
split). The CF1 India lane keeps its own Q2 `li_weekly`/`CF1_CS_TARGET` plan (no Q3 supplied).

**Since `.venv` may be broken / ADC unauthed, reload the seed with `bq` (gcloud creds, no venv) —
`bq load` of ONLY `real_targets` is safer than `seed_static.py`, which also loads the gitignored
`tiers.csv`/`line_cf.csv` and fails if `data/` is absent:**

```powershell
$env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"      # gcloud auth login first if the token expired
bq --project_id=bidbrain-analytics --location=australia-southeast1 load `
  --replace --source_format=CSV --skip_leading_rows=1 --allow_quoted_newlines `
  client_cloudflare.seed_real_targets "clients/client_cloudflare/targets/real_targets.csv" `
  WEEK:INTEGER,DATE:DATE,TIER:STRING,REGION:STRING,COUNTRY:STRING,TARGET:INTEGER
gcloud run jobs execute cloudflare-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait
```
Then rebuild + deploy the dash service (see CLAUDE.md → *Redeploy after an edit*).

### 11 media-plan market chips + a non-displayed OTHER residual (2026-06-25 rework; KR reverted 2026-07-02)

The CS markets are the client's media-plan grain — **11 market chips**, plus a residual `OTHER` that is
**not a chip** (so it's excluded from the dashboard). Defined in `sql/10_salesforce_leads_live.sql`'s
`REGION_GRP` and carried straight through `sql/13_pacing_model.sql` (`MARKET_REGION = REGION_GRP`):

**`AU`, `NZ`, `SIM` (SG/MY/ID), `RoA` (TH/VN/PH), `SAARC` (IN), `GCR-CN`, `GCR-TW`, `GCR-HK`, `KR`,
`RIG`, `JP`.** The old 7 chips (ANZ/ASEAN/GCR) were split to match the target sheet 1:1.

- **Korea Leads (KR)** — Country `'Korea, Republic of'` leads in the **6 ORIGINAL El\* CS campaigns
  ONLY** (3 Roverpath + 3 Final Funnel Lead-Gen; seed-driven via `seed_kr_campaign_ids`). ~**164** leads.
  **2026-07-02:** reverted the 2026-06-25 "ALL Korea in the 12 campaigns" rule at the client's request —
  Korea now counts only these 6. Korea leads from the other 6 campaigns (Connectivity Cloud / Modernize
  Security / Modernize Applications, ~55 live 2026-07-02) fall through to `OTHER`. (Total Korea in the 12
  CS campaigns = 219: 164 in the 6 → KR, 55 outside → OTHER.)
- **RIG Leads (RIG)** — **NON-Korea AND** `ASSET_2` `IN ('A-MAM-2','A-MAM-3')` (the gaming-vertical
  *Modernize Applications* asset — only `A-MAM-3` has data) **AND** the **3 Final Funnel** campaigns.
  Asset-based, evaluated **before** geography, so it spans every country. Live count **180** (167 accepted).

The geographic markets are pure `COUNTRY_NAME` maps, **case-normalised** (`UPPER(TRIM(COUNTRY_NAME))`)
so mis-cased countries (`japan`, `Hong kong`, `india`) route to JP / GCR-HK / SAARC instead of falling
to a residual. The `ELSE 'OTHER'` arm holds Korea leads outside the 6 KR campaigns (~55) plus any
brand-new/unmapped country. `OTHER` is **not one of the 11 chips**, so those leads are excluded from the
dash — the headline CS totals sum over the chips, so there is no total-vs-sum drift on screen (this
matches the pre-2026-06-25 behaviour; the ~55 leftover Korea leads just aren't counted anywhere on the
dash). Add `OTHER` to `ALL_MARKETS` in `dash/dashboard.html` if those leads should become visible.
The old `pacing_model` "Computer Games + Tier 2 → RIG" override was removed so RIG equals the exact def.
The reference DDL `snowflake_v_salesforce_leads_live.sql` (Transmission's / Cloudflare's legacy R2 export,
NOT our pipeline) keeps the geographic logic, but its KR arm was **also campaign-scoped to the 6**
(2026-07-02) — that file is a **manual Snowflake DDL our read-only roles can't apply**, so it needs an
owner/ACCOUNTADMIN to run the `CREATE OR REPLACE` (keep the `copy grants`) before Transmission's own view
matches. The **status dashboard** reproduces KR / RIG + **reconciles the `OTHER` residual** straight from
Snowflake; its core CS counts (Total / Accepted / Rejected / New) query the whole 12-campaign universe
with **no region filter** (so they include the ~55 OTHER leads the dash omits).

**Targets follow the media-plan sheet** per market (Q2 total **3216**: AU 1150 / NZ 127 / SIM 381 /
RoA 165 / SAARC 282 / GCR-CN 106 / GCR-TW 106 / GCR-HK 204 / KR 202 / RIG 172 / JP 321), and now live
as a **version-controlled committed CSV** (`targets/real_targets.csv` → `seed_real_targets`, the
per-client "targets in BQ from a committed CSV" standard — see *Updating targets* below).

## The data contract (`cloudflare.json` -> `/data.json`)

```json
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",
  "paid_media": {
    "row_count": 0,
    "window": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { "channel","date","week_start","market","imps","clicks","spend_usd",
                "leads","form_opens","link_clicks","action_clicks","video_starts",
                "video_completions","spend_jpy","fx_usd_jpy" } ],
    "creatives": [ { "channel","market","creative","imps","clicks","spend_usd","leads" } ],
    "benchmarks":        { "<channel>": { "ctr","cpm","cpc" } },
    "benchmarks_market": { "<market>":  { "ctr","cpm","cpc" } },
    "li_weekly": [ { "week","period","week_start","target","cum_target" } ]
  },
  "pacing": {
    "row_count": 0,
    "rows": [ /* every column of V_PACING_FINAL_MODEL, dates as ISO strings */ ]
  },
  "campaigns": {
    "peyc":        { "label","campaign_group","window","totals","daily":[…],"by_campaign":[…] },
    "cf1_india":   { …same…, "cs": { "target":110,"metric","accepted","rejected","new","total",
                                      "reviewed","data_through","by_publisher":[…],"by_region":[…],"daily":[…] } },
    "coles_hyper": { … }
  }
}
```

`dashboard.html` reads `paid_media` exactly like the old `paid_media.json`
(`adaptPayload` is unchanged) and `pacing.rows` exactly like the old
`pacing.json` (`rawRows`). The `paid_media.creatives[]` array (creative-grain
delivery) powers the "Top & bottom performing creatives" tables — **these rows
carry NO `date`, so the dashboard filters them by the market chips ONLY, never the
date range** (`renderCreativeTables` uses `paidMediaActiveMarkets.has(r.market)`, NOT
`passesAll()`, whose `dateOk(undefined)` would silently blank the tables). Their
`market` is raw TTD `MARKET_L3` (e.g. `HKTW`, `CN`, `AUNZ`, `SGMYIDPHTH`), so every
token must be in `PM_MARKET_REMAP` or the row falls outside the 7 L1 buckets and
drops. `campaigns`
powers the three single-campaign LinkedIn dashboards selectable in the top-bar
dropdown (read from the shared `raw_snowflake.linkedin_ads_apac` mirror, not from
Snowflake directly). **CF1 also carries a content-syndication lane** (`campaigns.cf1_india.cs`,
from `sql/14_cf1_cs`): "Double Touch MQLs" vs a **110 target** — accepted/rejected, by
publisher/region, and a cumulative-delivery line keyed on the lead `DAY`. It's the 2 CF1
CS campaign IDs (vendors→CaptureIQ→Integrate→Salesforce; also in the core 12-ID filter, but
this is a separate CF1-scoped view). In the UI the CF1 single-campaign view is split into two
**tabs** (`#cmpTabs`, mirroring the Core dashboard's tab pattern): **LinkedIn Paid Media**
(`#cmpLI`, default) and **Content Syndication** (`#cmpCS`). `setupCmpTabs()` shows the tab bar
only when a campaign has a `cs` block — peyc/coles_hyper have none, so they stay a single
LinkedIn view with no tabs. `switchCmpTab()` toggles the panels and `.resize()`s the charts
(Chart.js can't size a canvas created while `display:none`). Target is the one knob
(`CF1_CS_TARGET` in `job/main.py`). `data_through` is the newest source `LAST_ALTERED` (true
data instant); `last_updated` is the build time. See `dash/DASHBOARD.md`.

**Channel / market labels must match the dashboard:** `benchmarks` keys must be
`TTD`, `LinkedIn`, `Reddit`, `LINE`; row `channel` must be one of
`LinkedIn`/`LI`, `TTD`/`TradeDesk`, `Reddit`, `LINE`; markets must be the seven
in `all_markets`. These come straight from the Snowflake views — if your view
emits different strings, fix it in `sql/` (the only place that maps them).

---

## One-time replicate / deploy order

Prereqs: `gcloud` authenticated; APIs enabled (`run`, `cloudbuild`,
`artifactregistry`, `bigquery`, `storage`, `secretmanager`); the Artifact
Registry docker repo `bidbrain` exists; the shared Snowflake key secret
`snowflake-bq-key` exists (same one MongoDB uses).

```bash
PROJECT=bidbrain-analytics
REGION=australia-southeast1

# 1. Private data bucket
gcloud storage buckets create gs://bidbrain-analytics-cloudflare-dash \
  --project $PROJECT --location $REGION --uniform-bucket-level-access

# 2. BigQuery dataset
bq --location=$REGION mk --dataset $PROJECT:client_cloudflare

# 3. Runtime service accounts
gcloud iam service-accounts create cloudflare-dash-job --project $PROJECT
gcloud iam service-accounts create cloudflare-dash-web --project $PROJECT
#   job: read/write its dataset + bucket, read the Snowflake key
bq update --dataset --source <(echo '{}') $PROJECT:client_cloudflare  # (or grant via IAM policy)
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
#   (also grant cloudflare-dash-job roles/bigquery.dataEditor on the client_cloudflare dataset)
#   web: read the bucket + its two secrets
gcloud storage buckets add-iam-policy-binding gs://bidbrain-analytics-cloudflare-dash \
  --member="serviceAccount:cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

# 4. Secrets
printf 'choose-a-dashboard-password' | gcloud secrets create cloudflare-dash-password --data-file=- --project $PROJECT
python -c "import secrets;print(secrets.token_urlsafe(48),end='')" | gcloud secrets create cloudflare-dash-session-key --data-file=- --project $PROJECT
#   grant both secrets to cloudflare-dash-web (roles/secretmanager.secretAccessor)
#   (the job is BQ-only now — it does NOT need snowflake-bq-key. pull_static.py does,
#    but that's a manual one-time local run, not the scheduled job.)

# 5. Seed the static tables into BigQuery. data/ is gitignored, so on a fresh checkout pull
#    the snapshots first (needs the Snowflake key); then load them to BQ (no Snowflake).
python clients/client_cloudflare/pull_static.py    # Snowflake -> data/*.csv (skip if data/ already present)
python clients/client_cloudflare/seed_static.py    # data/*.csv -> client_cloudflare.seed_*

# 6. Apply the BigQuery model views (needs the seeds + raw_snowflake.* mirrors to exist)
python clients/client_cloudflare/create_views.py

# 7. Run the job — reads the views, produces cloudflare.json in GCS (no Snowflake)
python clients/client_cloudflare/job/main.py

# 8. Build dashboard.html from your existing index.html (see dash/DASHBOARD.md)

# 9. Deploy the SERVICE — build the image, then deploy as yourself.
#    (Do NOT `gcloud builds submit --config .../cloudbuild.yaml` from a laptop: it fails
#     with iam.serviceaccounts.actAs because Cloud Build's SA can't act as the runtime SA.
#     The cloudbuild.yaml files are for a future push-to-main trigger only.)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-dash:$(git rev-parse --short HEAD)
gcloud builds submit clients/client_cloudflare/dash --tag $IMG --region $REGION
gcloud run services update cloudflare-dash --image $IMG --region $REGION \
  --service-account cloudflare-dash-web@$PROJECT.iam.gserviceaccount.com \
  --set-env-vars=GCS_BUCKET=bidbrain-analytics-cloudflare-dash,DATA_OBJECT=cloudflare.json \
  --set-secrets=DASH_PASSWORD=cloudflare-dash-password:latest,SESSION_SECRET=cloudflare-dash-session-key:latest \
  --memory=512Mi
gcloud run services update cloudflare-dash --region $REGION --no-invoker-iam-check  # org policy: app does its own auth

#10. Deploy the JOB the same way (or just keep running it locally while testing)
IMG=australia-southeast1-docker.pkg.dev/$PROJECT/bidbrain/cloudflare-export:$(git rev-parse --short HEAD)
gcloud builds submit clients/client_cloudflare/job --tag $IMG --region $REGION
gcloud run jobs deploy cloudflare-export --image $IMG --region $REGION \
  --service-account cloudflare-dash-job@$PROJECT.iam.gserviceaccount.com --memory 1Gi
```

Then, mirroring MongoDB:
- **Freshness-gated run** — Cloud Scheduler trigger executing the `cloudflare-export`
  job every `*/10` (UTC). Run [`scheduler.ps1`](scheduler.ps1). The job is **self-gating**:
  each tick it cheaply probes `INFORMATION_SCHEMA.TABLES.LAST_ALTERED` for its four upstream
  Snowflake tables (metadata-only — no warehouse credits) and only does the full rebuild +
  upload when one advanced, recording a `_freshness.json` watermark in the bucket. So the
  dashboard refreshes **within ~10 min of new data** instead of at a fixed 22:00 UTC, while
  most ticks are a ~3s no-op. The payload carries both `last_updated` (build time) and
  `data_through` (newest source `LAST_ALTERED`). Re-running [`seed_static.py`](seed_static.py)
  changes a *static* input that the gate doesn't watch, so kick the job once by hand after it
  (`gcloud run jobs execute cloudflare-export --region australia-southeast1 --wait`). See
  [`job/README.md`](job/README.md#freshness-gate--why-most-runs-do-nothing-and-thats-the-point).
- **Access path** — via the platform front-door at `https://dashboards.bidbrain.ai/d/cloudflare/`
  (one login over all dashboards; the front-door reverse-proxies this service). There is no
  `cloudflare.bidbrain.ai` subdomain. See `dash/LIVE_URL.md`.
- **CD (future, not active)** — the per-unit `cloudbuild.yaml` files are wiring
  for two push-to-`^main$` Cloud Build triggers (included files
  `clients/client_cloudflare/job/**` and `clients/client_cloudflare/dash/**`). Not enabled yet;
  redeploys today use the manual build-then-deploy steps above.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template this client is based on (and diverges from).
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — the shared raw layer this client now reads (`salesforce_cs_apac_all`, `tradedesk_apac_all`, `linkedin_ads_apac`, `reddit_ads_apac_all`), like every other client.
