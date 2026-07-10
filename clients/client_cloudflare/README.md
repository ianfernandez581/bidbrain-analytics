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

**Q3 FY26 targets — ADDED (2026-07-09), client-confirmed.** The client's Core DG Lead Pacing plan
(`Raw Files/CF_FY26 Q3_Core DG Lead Pacing(Target Format Needed).csv`) was transformed into the seed
format and appended to `targets/real_targets.csv`, so it now carries **Q2 + Q3** rows (Q2 weeks
`2026-03-30 → 2026-06-15`, Q3 weeks `2026-07-06 → 2026-09-28`, 13 weeks). Q3 grand total **2290**
(ANZ 943 / ASEAN 419 / SAARC 220 / GCR 309 / JP 244 / KR 155), reconciled to the plan's own total row.
The dashboard **defaults to Q2** (2026-07-09), and selecting Q3 lights up its target KPIs + pacing cards
from these targets. **The target is quarter-anchored** (the full selected-quarter plan, NOT the in-range
sum) — otherwise, because the date range clamps to the last day with data, an in-progress quarter like
Q3 would show only the elapsed weeks' target (the "Q3 Target = 182 instead of 2290" bug, fixed
2026-07-09 via `pacingWindow`/`quarterTargets` in `aggregate()`). **Note: the Q3 "Core DG" plan has NO
RIG line**, so the RIG chip shows Q3 actuals with no target — that's the client's scope, not a bug. The
raw plan put each ANZ/ASEAN region total on its lead country (Australia / SIM) and left NZ / RoA blank
(seeded as `0`); the `targets_v2_norm` view sums per region so the roll-up is unaffected. To change Q3,
edit `targets/real_targets.csv`, re-seed (`seed_static.py` / the `bq load` below) and run the job with
`FORCE_REBUILD=1`. The CF1 India lane keeps its own Q2 `li_weekly`/`CF1_CS_TARGET` plan (unaffected).

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

### 7 coarse market groups (2026-07-07 rollback of the 2026-06-25 11-chip split, per the Jade call)

The CS markets are the **coarse 7 groups**, plus a residual `OTHER` that is **not a chip** (so it's
excluded from the dashboard). Defined in `sql/10_salesforce_leads_live.sql`'s `REGION_GRP` and carried
straight through `sql/13_pacing_model.sql` (`MARKET_REGION = REGION_GRP`); targets are rolled up to the
same 7 in `sql/12_targets_v2_norm.sql`:

**`ANZ` (AU+NZ), `ASEAN` (SG/MY/ID/TH/VN/PH), `SAARC` (IN), `GCR` (CN/TW/HK), `KR`, `JP`, `RIG`.**
This **rolls back** the 2026-06-25 split (which had broken these into 11 chips) at the client's request,
so CS markets now match the paid-media L3 grain 1:1 (dashboard `ALL_MARKETS` + `PAID_ALL_MARKETS` are
identical). Rolling REGION_GRP back to coarse also re-activates the `ANZ`/`ASEAN`/`GCR` accepted-lead
columns in `sql/13` (they had silently gone to zero under the 11-chip codes).

### 2026-07-07 changes from the Jade call (test leads, unprocessed, quarter labels)

- **Test leads excluded.** `sql/10` now drops any lead whose email DOMAIN contains `transmission`
  (`... AND LOWER(IFNULL(SPLIT(EMAIL,'@')[SAFE_OFFSET(1)],'')) NOT LIKE '%transmission%'`). The vendors
  were each sent ≥2 test leads on Transmission emails (Nabeel / Shalvi / Jade), which were inflating the
  Q3 rejection rate (~36%). The SAME filter is mirrored into the status dashboard's Cloudflare CS check
  (`status_dashboard/job/main.py`, `_CF_TEST_LEAD_FILTER`) so the accuracy monitor doesn't false-alarm.
- **Unprocessed / New leads removed from the dashboard.** They're our internal backlog, not shown to
  Cloudflare. Acceptance & rejection rate now use **reviewed = accepted + rejected** as the denominator
  (so acc% + rej% = 100%); the unprocessed pacing bar, the "pending triage" note, the Comparison-tab
  Unprocessed % KPI, and the QoQ status-mix New row are all gone. The `cs_qoq` view still emits `New`
  (harmless; the front-end ignores it). Overview "Total leads" was relabelled **"Accepted leads"** (the
  KPI always showed the accepted count).
- **Quarter captions are dynamic.** Captions must not hardcode a quarter (the default was Q3 at the
  time, showing a Q2-labelled plan). Captions follow the selected quarter via `qtrLabel()` (returns
  `Q3` / `Q2` / `Q2-Q3`, or `Quarter` for a custom range) applied to every `.qlbl` span + the JS-built
  labels (`renderProgress` / `renderLeadsTarget` / by-region summary / date-scope banner). The QoQ tab
  gained a caveat line ("Q3 campaigns launched late, so QTD reads light — timing, not a data issue").

### Dev mode (internal) - unprocessed leads + Source-ID filter (2026-07-10)

The unprocessed/New leads removed above (client rule) are still viewable INTERNALLY via a role-gated
**Dev mode** toggle on the CS Overview toolbar. It is **hidden from clients**: it appears only when the
platform proxy injected `window.BB_DEV=true` - which it does for an **admin / super-admin** session or
the **Transmission agency** portal (see `bidbrain-platform/dash/main.py` `_dev_flag_script`, injected
alongside `window.BB_SPEND_MULT`). A `?dev=1` URL param is a fallback for direct (non-proxied) access.
Dev mode is **OFF by default**, so the client-facing view is byte-for-byte unchanged.

When ON it (a) surfaces the unprocessed backlog across **all** CS Overview charts - an "Unprocessed"
KPI in the Overall group, a stacked bar on the pacing chart, an unprocessed line on the Accepted-leads
trend, an Unprocessed bar per market card, and New leads folded into the Solutions / Country /
demographic / asset composition donuts (centre totals become accepted + unprocessed); and (b) exposes a
**Source-ID (campaign) dropdown** that filters the CS view to a single `CAMPAIGN_ID`. The filter applies
to LEADS only - the plan/target stays at the market grain - and the acceptance/rejection rate denominator
stays reviewed-only (unchanged). All of this is frontend-only (`dash/dashboard.html`): `devMode` +
`selCampaignId` globals gate it, `aggregate()` is the single choke point, and it reads New leads already
present in `pacing.rows[]`.

### Korea reconciliation (144 vs 164) — Ian to confirm with data

The client (Nabeel) reports **164 Korea leads DELIVERED** (101 Final Funnel + 63 Roverpath); the dash
KR chip shows **~144**, which is Korea **ACCEPTED** leads. The ~20 gap is almost certainly
delivered-vs-accepted (rejected + new Korea leads), **not** a country-name or campaign-scoping bug — so
`sql/10` keeps the exact `= 'KOREA, REPUBLIC OF'` match (a broadened `LIKE '%KOREA%'` would over-count
AND desync the status-dash check). Confirm the split before changing anything:

```sql
SELECT
  CASE WHEN LEAD_STATUS IN ('Accepted','Replied','Unresponsive') THEN 'Accepted'
       WHEN LEAD_STATUS = 'Rejected' THEN 'Rejected' ELSE 'New/other' END AS bucket,
  CASE WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN','701RG00001ElTu3YAF','701RG00001ElVXdYAN') THEN 'Roverpath'
       WHEN CAMPAIGN_ID IN ('701RG00001ElUoXYAV','701RG00001ElUa0YAF','701RG00001ElNYkYAN') THEN 'Final Funnel' END AS publisher,
  COUNT(*) AS leads
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
WHERE UPPER(TRIM(COUNTRY_NAME)) = 'KOREA, REPUBLIC OF'
  AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`)
  AND LOWER(IFNULL(SPLIT(EMAIL,'@')[SAFE_OFFSET(1)],'')) NOT LIKE '%transmission%'
GROUP BY 1, 2 ORDER BY 2, 1;
```

If the total across all buckets ≈ 164 and Accepted ≈ 144, the dash is correct and the client is
quoting *delivered*; frame it that way rather than changing the KR logic. Also try the same query with
country variants (`LIKE '%KOREA%'`) — if that adds ~20 *accepted*, the fix is a broadened match (apply
it in BOTH `sql/10` and the status check's KR arm to stay in sync).

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
Snowflake; its core CS counts (Total / Accepted / Rejected / New) query the whole 13-campaign universe
with **no region filter** (so they include the ~55 OTHER leads the dash omits).

**Targets follow the media-plan sheet** per market (Q2 total **3216**: AU 1150 / NZ 127 / SIM 381 /
RoA 165 / SAARC 282 / GCR-CN 106 / GCR-TW 106 / GCR-HK 204 / KR 202 / RIG 172 / JP 321), and now live
as a **version-controlled committed CSV** (`targets/real_targets.csv` → `seed_real_targets`, the
per-client "targets in BQ from a committed CSV" standard — see *Updating targets* below).

### Quarter filter (Q2 / Q3) — defaults to Q2

The top bar carries a **Quarter** toggle (Q2 · Apr–Jun / Q3 · Jul–Sep) that **defaults to Q2**
(2026-07-09). It's a coarse control layered over the shared Looker-style date-range picker: quarters
are **contiguous calendar spans**, so a selection maps 1:1 onto a single date range — Q3 → `[Jul 1,
dataMax]`, Q2 → `[Apr 1, Jun 30]`. The **date range is the single source of truth**; the chips are
*derived* from it (`syncQuarterChips`), so picking an arbitrary range in the calendar simply lights
no chip ("custom"). **Both chips are ALWAYS visible**, and the active quarter is highlighted. **The
chips are SINGLE-SELECT:** clicking one jumps the range to exactly that quarter (`toggleQuarter` sets
the span). The **Q2+Q3 union** (`[Apr 1, dataMax]`, labelled "Q2-Q3") is reachable by selecting a
spanning range in the calendar; `syncQuarterChips` still detects + labels it.

**RIG drops out of the MARKETS filter under Q3** (client request 2026-07-09 — "remove the RIG filter
option when Q3 is toggled"): the Core DG Q3 plan carries **no RIG line**, so `visibleMarkets()` hides
the RIG chip AND excludes RIG from the data (`matchMarket` + the by-region grid) when Q3 is the active
quarter (Q3 selected, not Q2). RIG stays under Q2 and the Q2+Q3 union (both have RIG Q2 data). In
practice Q3 has zero RIG rows anyway, so this only removes an irrelevant chip — no headline number
changes. (The CS Comparison tab's A/B region dropdowns are NOT yet quarter-scoped, so they still list
RIG; low priority.)

The filter is **global** — it drives Paid Media, Content Syndication and CS Comparison alike (the QoQ
tab is Q3-vs-Q2 by construction and ignores the range). Implemented entirely in `dash/dashboard.html`
(`QUARTERS`/`quarterSpan`/`toggleQuarter`/`syncQuarterChips`/`renderQuarterChips`/`visibleMarkets`
+ `DateRange.setRange` + `q2`/`q3` calendar presets); no data-layer change.

**Q3 targets/pacing are loaded (2026-07-09).** The Q3 target rows are in `seed_real_targets`, so the
Q3 view now shows real target KPIs + the two pacing cards (`renderLeadsTarget`, `renderProgress`). The
target-less placeholder (target KPIs `—`, *"Targets & pacing not set for the selected period yet —
showing actuals only"*) still fires automatically for any span with no `ALLOCATED_TARGET` rows (e.g.
a custom range past Q3, or RIG under Q3 — the Core DG plan has no RIG line). To reload targets: edit
`targets/real_targets.csv` → `seed_static.py` (or the targeted `bq load`) → job `FORCE_REBUILD=1`; the
pacing UI reflects it on the next build (the service serves the bucket live, so **no dashboard redeploy
is needed** unless `dashboard.html` itself changed).

**Target KPIs + the "Pacing - target vs actual" chart are QUARTER-ANCHORED, not range-clamped
(2026-07-09).** The shared date range clamps to the last day that has data, so for an in-progress
quarter (Q3, data only to ~week 1) a range-clamped target/pacing would show only the elapsed weeks
(the "Q3 Target = 182 instead of 2290" / "Q3 pacing chart shows only week 1" bugs). Fix: `aggregate()`
computes the target over the full selected-quarter span via `pacingWindow()`/`quarterTargets` (headline
`q2Target`, `ttdTarget`, `regionRows`), and a dedicated **`pacingDaily`** series (also full-quarter)
backs `renderWeekly` so Q3 shows every one of its 13 plan weeks like Q2 shows 12. Actuals still appear
only where leads exist (future weeks carry target + 0 actual; a small pre-plan-week bucket holds any
leads that arrived before the plan's first Monday). The daily accepted-leads line (`renderDaily`) and
the CS Comparison panels still read the in-range `dailyFull`/`weekly`. **The pacing chart deviates from
the repo-wide chart-toggle defaults** (CLAUDE.md): it defaults to **Absolute** (not Relative) and has
**Month/Week only** (no Day grain) - client request 2026-07-09.

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
CS campaign IDs (vendors→CaptureIQ→Integrate→Salesforce; also in the core 13-ID filter, but
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
