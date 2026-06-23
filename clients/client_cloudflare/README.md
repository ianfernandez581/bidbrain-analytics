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
  -> Cloudflare CNAME  cloudflare.bidbrain.ai (proxied) -> *.run.app
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
  `seed_*` (`seed_static.py`).
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

### KR + RIG are client-defined CS segments (2026-06-19) — not geographic

The **KR** and **RIG** CS buckets are no longer the old purely-geographic regions. They are
the client's exact lead definitions, redefined in `sql/10_salesforce_leads_live.sql`'s `REGION_GRP`
(and carried straight through `sql/13_pacing_model.sql`, `MARKET_REGION = REGION_GRP`):

- **Korea Leads (KR)** — Country `'Korea, Republic of'` **AND** the **6 original El\*** campaigns
  only (3 Roverpath + 3 Final Funnel). Korea leads from the Connectivity-Cloud / Modernize campaigns
  are deliberately **excluded**. Live count **164** (137 accepted).
- **RIG Leads (RIG)** — **NON-Korea AND** `ASSET_2` ("Asset Title 2" in Salesforce) `IN ('A-MAM-2','A-MAM-3')`
  (the gaming-vertical *Modernize Applications* asset — only `A-MAM-3` has data today) **AND** the
  **3 Final Funnel** campaigns. RIG is **asset-based, not geographic**, so it spans every country and is
  evaluated **before** the five geographic buckets — it pulls those leads out of ANZ/ASEAN/SAARC/GCR/JP
  (intentional overlap, accepted by the client). Live count **180** (167 accepted).

The other five regions stay purely geographic. The redefinition leaves a small residual **`OTHER`**
bucket (~42 leads — mostly Korea-from-Modernize-Security + a few mis-cased / off-plan countries). As of
**2026-06-23** `OTHER` is the **8th entry in the dash CS `ALL_MARKETS`** and renders as the **"Others"**
market tab/chip (label only — the underlying `MARKET_REGION` stays `'OTHER'`), so CS totals are now
**complete**: Accepted = **3328** (was 3309 when OTHER was dropped). It carries no Q2 target, so its
By-region card shows only the QTD-Accepted bar. The old `pacing_model` "Computer Games + Tier 2 → RIG"
override was removed so RIG equals the exact client def. The reference DDL
`snowflake_v_salesforce_leads_live.sql` (Cloudflare's own legacy R2 export, NOT our pipeline) keeps the
OLD geographic logic — our BQ region logic now **diverges** from it. The **status dashboard** reproduces
KR / RIG / **Others** straight from Snowflake, and its core CS counts (Total / Accepted / Rejected / New)
now query the raw 12-campaign universe with **no region filter** (so they include the OTHER residual too).
**Pacing caveat:** RIG/KR target rows in the seed are still keyed by the old region names, so the RIG
pacing % (actual-vs-target) compares the new asset-based RIG actuals against the legacy RIG target —
the *counts* are exact, the pacing ratio is indicative until the client supplies segment-specific targets.

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
- **Friendly URL** — Cloudflare CNAME `cloudflare.bidbrain.ai` -> the service's
  `*.run.app` host, Proxied, SSL Full (strict), Host Header Override. See
  `dash/LIVE_URL.md`.
- **CD (future, not active)** — the per-unit `cloudbuild.yaml` files are wiring
  for two push-to-`^main$` Cloud Build triggers (included files
  `clients/client_cloudflare/job/**` and `clients/client_cloudflare/dash/**`). Not enabled yet;
  redeploys today use the manual build-then-deploy steps above.

## See also

- [Root README](../../README.md) — the whole-platform map, security model, and naming conventions.
- [`../client_mongodb/`](../client_mongodb/README.md) — the template this client is based on (and diverges from).
- [`../snowflake_data_pull/`](../../ingest/snowflake_data_pull/README.md) — the shared raw layer this client now reads (`salesforce_cs_apac_all`, `tradedesk_apac_all`, `linkedin_ads_apac`, `reddit_ads_apac_all`), like every other client.
