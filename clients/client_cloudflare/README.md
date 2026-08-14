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
The dashboard **opens on Q3** (2026-08-05; it defaulted to Q2 from 2026-07-09), so these Q3 targets drive
the target KPIs + pacing cards on load. **The target is quarter-anchored** (the full selected-quarter plan, NOT the in-range
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

### Brief-number campaign prefixes broke paid-media market parsing (FIXED 2026-08-04)

Transmission is progressively renaming campaigns with a leading brief number (`1160_`, `2103_`,
`2479_` ...). Trade Desk market derivation was a **fixed offset** into the underscore-split name, so
every token shifted one position: `MARKET_L3` came back as `APAC-ANZ` instead of `ANZ`, `JAPAN-JPN`
instead of `JP`. Those are non-empty, so the rows passed `paid_media_model`'s `MARKET_L3 <> ''`
guard, landed in `paid_media.rows[]`, and then matched **no** dashboard market chip - and
`passesAll()` in `dash/dashboard.html` filters every aggregate by chip. Silent loss, no error.

Two leaks, both closed:

| leak | imps | why | fix |
|---|---:|---|---|
| off-chip after remap | 4,989,809 | prefix shifted the offset (`APAC-*`, `JAPAN-JPN`); plus `TW`/`HK` were never in `PM_MARKET_REMAP` | parse off `CAMPAIGN_NAME_NORM`; add `TW`/`HK` → `GCR` |
| dropped at the model | 7,360,518 | short-form names (DOOH / High Impact, Q2 May-Jun) have no offset-8 token at all | `" - AU"/" - NZ"/" - ANZ"` suffix fallback in `03_stg_tradedesk.sql` |

**Trade Desk impressions rendered on the dash: 23,702,942 → 36,053,269 (+52%).** Spend and clicks
move with it. The second row is Q2 history that was never displayed before, so Q2 totals change; to
revert just that part, delete the suffix-fallback `CASE` arm in `03_stg_tradedesk.sql`.

### DOOH excluded from the dashboard (2026-08-05, client request)

The suffix-fallback fix above surfaced the two Q2 DOOH campaigns (`CLOUD_ACQ_2026-Q2-DOOH - AU`/
`- NZ`, ran 2026-05-12 → 05-31: 12 creatives, **1,362,226 imps / $19,799.59 / 0 clicks**). DOOH is
out-of-home - it structurally cannot click - so all 12 creatives sat at 0% CTR and filled the
whole bottom-10 creatives table (which is whole-flight, not date-scoped, so they showed even under
Q3). Client asked for **full removal**: `03_stg_tradedesk.sql` drops any campaign whose RAW name
contains `dooh` (substring, so brief-number prefixes can't dodge it), which removes DOOH from
spend, imps and every KPI/chart/creative table (both `paid_media_model` and `paid_creatives_model`
read that view). Q3 KPIs don't move (DOOH ended in May); Q2 totals drop by the figures above.
**Mirrored** as an explicit `NOT ILIKE '%DOOH%'` in the two whole-advertiser TTD checks in
`status_dashboard/job/main.py` - keep both sides in sync or the accuracy monitor goes red. The
sibling short-form campaign `High Impact--HyperlocalGeo - ANZ` (5,998,292 imps / $9,900.01 /
1,923 clicks) is real clickable display and **stays**. To revert: delete the `NOT LIKE '%dooh%'`
predicate in the view + the two `NOT ILIKE` lines in the status checks.

The same campaign exists under **both** name forms in the feed (15 raw names = 8 real campaigns for
the Q3 MDS line), so any name-keyed aggregate was also splitting in half. Normalising unions them.
Reference figure to check against, from the media-buyer sheet pull: the 8 `*_MDS_TTD_*COREDG-Q3`
campaigns = **5,516,027 imps / 4,788 clicks / $14,499.98**.

**LinkedIn was hardened the same way but no number changed** (3,746,467 / 16,908 / 487 before and
after). Its `CAMPAIGN_NAME` is the *ad set* name, which has not been renamed yet; the parent campaign
names in the sheet already carry prefixes, and a rename would have zeroed the channel via
`STARTS_WITH(CAMPAIGN_NAME,'CLOUD_ACQ_')`. That now reads `CAMPAIGN_NAME_NORM`.

**Google Ads is NOT wireable yet.** The sheet's Cloudflare Google Ads campaign
(`CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting`, id `24037386856`) appears in **none** of our
sources - 0/28 name overlap against `raw_snowflake.google_ads_apac`, `raw_google_ads.perf_google_ads`
(native DTS) and `raw_windsor.perf_google_ads`. That account is not ingested at all. It needs linking
to MCC 345-189-6252 + a DTS transfer before a Google Ads lane can exist here.

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
  **`sql/14_cf1_cs` was MISSED by this change and fixed 2026-08-09** — the CF1 Double-Touch lane predates
  the filter, so 3 Transmission test leads were reported as CF1 rejections (**20 instead of 17**, rejection
  rate 14.1% -> the true 12.2%; `reviewed` 142 -> 139). Accepted was unaffected (no test lead is Accepted),
  which is why only the one check went red. **Any new CS lane must carry this filter** — the status dash's
  CF1 checks had it on the source side from day one and are what caught the gap. Keep the two identical.
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

### Q2-only campaigns - the 4 P* Surround-ABM/Modernize ids capped at Q2 (2026-08-05)

Client request (via Transmission): the 4 P* campaigns (`701RG00001PXLpxYAH` / `701RG00001PXHnzYAH`
Roverpath Modernize Applications, `701RG00001PXNyDYAX` / `701RG00001PWX5gYAH` Final Funnel ABM
Modernize Security) are **Q2 campaigns that still receive REPLACEMENT leads** for rejected Q2 leads.
Replacements land with **Q3 created dates** (`DAY`), and since the dashboard buckets quarters by
created date they were surfacing on the Q3 side. Fix: a **date cap, not removal** - the ids stay in
`cs_campaigns` (Q2 history untouched), but a new `definitions.json` block **`cs_q2_only_campaigns`**
(cutoff `2026-07-01`) seeds `seed_cs_q2_only_campaign_ids`, and `sql/10`'s WHERE excludes their leads
with `DAY >= DATE '2026-07-01'` **everywhere** (CS Overview, QoQ Q3 side, pacing, lead table, CSV).
The status verifier builds the SAME cap from the same file (`_cf_cs_cte` in
`status_dashboard/job/main.py`), so the accuracy checks stay green. Caveats: replacement leads created
on/after Jul 1 appear **nowhere** (they don't backfill Q2 - the quarter is still a created-date range),
and the cutoff date is a mirrored literal in `sql/10` (change it in both files together). To lift the
cap, empty the `campaigns` list in `cs_q2_only_campaigns` and re-run `definitions_seed.py`.

### Admin View (internal) - unprocessed leads + Source-ID filter (2026-07-10)

The unprocessed/New leads removed above (client rule) are still viewable INTERNALLY via a role-gated
**Client View / Admin View** toggle in the **topbar** (a pill toggle, right of the date picker - it
reuses the `.qtr-*` CSS of the retired Q2/Q3 quarter control, which is why that CSS stays). **Client View** = exactly what the client sees; **Admin View** turns
on everything below. It is **hidden from clients**: the toggle appears only when the platform proxy
injected `window.BB_DEV=true` - which it does for an **admin / super-admin** session or the
**Transmission agency** portal (see `bidbrain-platform/dash/main.py` `_dev_flag_script`, injected
alongside `window.BB_SPEND_MULT`). A `?dev=1` URL param is a fallback for direct (non-proxied) access.
(Internally the flag is still `devMode`; Admin View = `devMode` true.)

Admin View **defaults ON** for a dev-allowed viewer (so you don't have to find the toggle); clients never
get `window.BB_DEV` so they only ever see Client View. When in Admin View it:

- **(a) Unprocessed across all CS Overview charts** - an "Unprocessed" KPI in the Overall group, a
  stacked bar on the pacing chart, an unprocessed line on the Accepted-leads trend, an Unprocessed bar
  per market card, and New leads folded into the Solutions / Country / demographic / asset composition
  donuts (centre totals become accepted + unprocessed).
- **(b) Source-ID (campaign) dropdown** that filters the CS view to a single `CAMPAIGN_ID`. LEADS only -
  the plan/target stays at the market grain; the acceptance/rejection rate denominator stays reviewed-only.
  Each option reads `<label> (<CAMPAIGN_ID>) - <n> leads`; the label comes from the `CAMPAIGN_LABELS`
  const in `dash/dashboard.html` (a MIRROR of `definitions.json` `cs_campaigns[].label` - keep in sync
  when that file changes), falling back to the raw Salesforce `CAMPAIGN` name for any unmapped ID.
- **(c) Lead-detail table** at the bottom of the CS Overview - every lead in the current filter with
  EVERY field we hold (Source ID, campaign, status, date, market, publisher/offer, company, title,
  country, name, email, phone, opt-in, lead id, raw timestamps, source file). Sortable + scrollable,
  capped at 1000 DOM rows, with a full-set **CSV export**. Contains PII, so it's `devMode`-gated (never
  client-facing). Frontend-only - the fields are already in `pacing.rows[]`.
- **(d) "Internal Notes" tab** (an Admin-View-only tab, hidden in Client View; **renamed from "Data
  from Transmission" 2026-08-05**) - an **Internal notes** card first (team notes with add/edit/delete;
  the UI is platform-injected into `#bbNotesMount` for staff sessions through dashboards.bidbrain.ai -
  empty on a raw run.app URL), then **what Transmission committed** in two tables: **Source IDs** (the canonical CS
  campaign/Source-ID list that should be present, from `definitions.json` / `seed_cs_campaign_ids`, with
  a **Label** column - the curated `CAMPAIGN_LABELS` name - plus a **Sample campaign** column (raw SF
  name), and what has actually landed per ID: leads / accepted / rejected / unprocessed + a Present?
  flag; a red row = committed but not yet delivering), and the **pacing plan** (the target numbers
  Transmission sent - `targets_v2_norm` over the committed `real_targets.csv` - per market x tier, Q2/Q3
  split + totals). **This one needs the job** (`build_transmission()` -> `transmission` in
  `cloudflare.json`), not just the frontend.

Frontend gating: `DEV_ALLOWED` (window.BB_DEV or ?dev=1) reveals the topbar toggle; `devMode` (Admin
View, default = `DEV_ALLOWED`) drives the Source-ID controls, the admin-only tab and the in-CS
unprocessed/lead-table rendering (`applyViewMode()` reflects the mode; `aggregate()` is the single
choke point). `setAdminView()` flips it.

### Spreadsheet-style tables (sort + search, 2026-07-10)

Every data table is **sortable** (the vendored `bb-sortable` engine - click a header) **and searchable**:
a small **Search table...** box is injected above each table with more than a handful of rows and
filters the data rows as you type (header + Total row always stay visible). Both survive the
`innerHTML` re-renders the dashboard does: a document-level `MutationObserver` re-wires new tables for
sorting and re-injects the search box (`window.bbEnsureSearch`), and each box's query is remembered per
host container so it persists across a rebuild. Grouped tables (colspan section-headers) and tiny
summary tables (< 6 data rows) are intentionally left without a search box. **Cloudflare-only for now** -
the search half is a local extension of the otherwise-vendored `bb-sortable`; it is NOT yet propagated
to the canonical copy (`clients/client_resetdata`) or the other dashboards.

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

### Re-skinned onto the MongoDB design language - dark glow, orange accent (2026-08-05)

Client request (JM): *"I like the overall style and format structure of the Mongo and Schneider
dashboards - the headers at the top, position of logos, navigation, the cleaner layout. Is it a
different design or layout used? What is different? I would ideally like the Mongo/SE design with
Orange as the background."*

**What was different.** MongoDB and Schneider run the newer **Bidbrain design system**, in two
variants of the same tokens:

| | canvas | cards | header | navigation |
|---|---|---|---|---|
| **MongoDB** | dark base (`--bg:#05131A`) + brand-accent glow | dark surfaces | agency wordmark · divider · **client logo** (supplied artwork, inlined) · Live | one **sticky glass control bar**: tab rail + exports + filters |
| **Schneider** | **brand colour AS the background** (deep green + 2 radial glows + arc pattern) | **WHITE, floating** with a green glow shadow | agency · divider · white logo chip · region tag · campaign select | tab rail in the bar |
| **Cloudflare (before)** | flat bright-orange gradient | white | **flat black bar**, wordmark knocked out in white, no chip | a white pill tab bar floating loose on the canvas + the date picker up in the topbar |

Both reference dashboards re-skin from a handful of CSS custom properties - that is the whole point
of the system, and it is why MongoDB's `:root` carries a literal *"change ONLY these to reskin
another client"* block.

**What Cloudflare adopted: the MongoDB dark-glow variant, on orange** (client picked it after seeing
both - *"I like the MongoDB more, the colouring, shading"*). A warm near-black base lit by orange
glow, near-white text on dark surfaces. Changes, all in `dash/dashboard.html`:

- **Tokens** - `:root` is now MongoDB's set (`--bg/--bg-2/--surface/--surface-2`, `--line/--line-2`,
  `--ink/--muted/--muted-2`) with `--brand-accent` = Cloudflare orange and orange `--glow*`.
  **Re-skinning another client is the accent block alone**, exactly as MongoDB's `:root` documents.
- **The legacy `--cf-*` names are REMAPPED onto those tokens** (`--cf-card:var(--surface)`,
  `--cf-bg:var(--surface-2)`, `--cf-line:var(--line)`, `--cf-ink:var(--ink)`, `--cf-mute:var(--muted)`)
  - MongoDB's own trick for its `--mdb-*` names. That one block flipped ~90% of the stylesheet with
  no edit; only hardcoded hex literals had to be chased (see below).
- **`--cf-navy` is now LIGHT** (`#E7D6C6`). It survives only as the dashed target-marker / "ahead of
  pace" colour on the progress + pacing bars; at its old near-black it was invisible on dark.
- **Body** - MongoDby's gradient recipe with orange: a glow blooming from the top, a second top-right,
  a warm lift bottom-left, over a near-black warm base. (The Schneider arc-pattern SVG was dropped.)
- **Header** - the Cloudflare mark is the **supplied artwork** (`creatives/Cloudlfare logo.jpg`, a white
  logo on its own orange field) **inlined as a base64 data URI** in `.logo-chip` -> `img.cf-logo`,
  height 36px. It replaced the hand-drawn SVG cloud + inked `CLOUDFLARE` wordmark on a white chip
  (2026-08-05); the chip no longer paints white, because a white surround would frame the artwork as
  an orange tile - so there is now **no white surface left** in the theme. **Inline, never a path:**
  the `dash/` Docker build context excludes `creatives/`, so a `src="..."` file reference or a `/logo`
  route would 404 in the deployed service. To swap it again, drop the new file in `creatives/` and
  re-inline it. MongoDB's surface-to-base topbar gradient with the accent glow spilling downward;
  the Transmission logo stays top-right, so there is no text agency wordmark.
- **Navigation** - a **sticky dark-glass `.control-bar`** holds the tab rail **and** the shared
  date-range picker + the internal View toggle, which used to live in the black topbar. Tabs use
  MongoDB's underline-on-a-hairline treatment (`.control-tabs`) with an accent drop-shadow.
- **Glow furniture** - MongoDB's `.kpi.accent` (accent bled into the surface + halo), glowing KPI
  stripes, `--shadow-card`, accent-tinted `tr.total`, and dark-tinted channel pills / callouts.
- **CHARTS ARE RE-THEMED** - the one part that is not just tokens, and the reason this variant is more
  work than the Schneider one:
  - **`Chart.defaults`** are set once, before any chart is built (`color`, `borderColor`,
    `scale.grid.color`, `scale.ticks.color`, legend label colour, tooltip bg/border/text). Chart.js
    defaults ticks and legends to `#666` and grid to near-black - invisible here. Doing it globally
    means **no chart can be left reading dark-on-dark**, including ones that never passed a colour.
  - Palette constants re-tuned: `PM_INK` (was `#1B2834` navy - would have vanished) → warm light;
    `PM_LINE`/`LINE` → `rgba(255,255,255,.09)`; `PM_LI` `#0A66C2`→`#3B93E8`, `PM_PURPLE`→`#B98AE8`,
    `PM_RD`/`PM_LN` brightened; `TARGET`/`PM_TARGET` → `#8A7263`; the 12-colour categorical `colors`
    array lost its three near-blacks; donut `borderColor:'#fff'` → the surface colour.

**No data, metric, chart, table or filter was added, removed or rewired** - shell, tokens and chart
colours only. Verified against the pre-re-skin file: **24 chart canvases before and after, all 163
element ids intact.** Gotchas worth knowing:

- `.dash-select` must keep a **SOLID** background: Chrome/Windows paints the native `<option>` list
  from the select's own background, so a translucent one renders white text on a near-white popup -
  invisible options, on the primary nav control. `option` colours are set explicitly for both the
  topbar select and the white-row dev select.
- The date picker's popover **anchors right** now (`.control-right .dp-pop{left:auto;right:0}`) - it
  sits on the right of the control bar, and left-anchored it opened off-screen.
- `#cmpTabs` (the CF1 campaign view's tab bar) reuses `.tabs`/`.tab` but sits **directly on the
  canvas** - single-campaign views have no control bar - so it takes the on-canvas colours. Without
  that override its ink text was unreadable on the orange.
- `switchDashboard()` hides `#controlBar` (not `.tabs`) for single-campaign views, since the shared
  date control lives in the bar too - hiding only the tabs would leave an empty glass strip.

### Surround ABM split out of Core DG - the lane model (2026-08-14, client request)

Brief **2193 "Surround ABM"** was summing into Core DG. It is a separate book with separate
numbers, so the client asked for it in the dropdown on its own. The dropdown now holds two KINDS
of entry, and this is the distinction to hold on to:

| kind | entries | renders |
|---|---|---|
| **PROGRAM lane** | `core` (Core DG APJ) · `surround_abm` (Surround ABM) | the FULL core shell - tab rail, shared date range, market chips - scoped to one brief |
| **CAMPAIGN lane** | `peyc` · `cf1_india` · `coles_hyper` | the single-campaign LinkedIn view (`renderCampaign`, whole-window totals, no date control) |

`core_emea` remains a disabled placeholder (see below) - it is a THIRD regional lane of the same
programme and still needs its own payload branch, which the program split does NOT give it.

**The split is a data-layer dimension, not a front-end filter over campaign names.** A `PROGRAM`
column flows the whole contract: `sql/03_stg_tradedesk` (+ `01_stg_linkedin`) → `05_paid_media_model`
/ `06_paid_creatives_model` → `job/main.py` `program` → `dashboard.html` `row.prog`. Values:

- **`CORE_DG`** - briefs 1160 (High Impact/HyperlocalGeo) / 2103 (Q2 Core DG) / 2479 (Q3 Core DG),
  plus all LinkedIn, Reddit and LINE. The `ELSE` arm, so a brand-new brief lands here rather than
  vanishing - it just needs splitting out once someone notices it.
- **`SURROUND_ABM`** - brief 2193: **Trade Desk only**, 5 campaigns
  (`..._{ANZ,ASEAN,GCR,KR,IN}-SURROUND-ABM`, TTD ids `6cm53fr` / `y2kxvxf` / `9lg1jx3` / `on8odve` /
  `hebzbzj`). Matched by **substring on the RAW name** (`'%surround%abm%'`, plus a `2193_` prefix
  arm) - never a fixed offset, and it spans both name vintages in the feed (the same campaign exists
  prefixed and un-prefixed - see the brief-number section above). Verified 2026-08-14: **10 distinct
  raw names = 5 campaigns x 2 vintages**, which is exactly why the substring rule is not optional.

**It is NOT a Q2 brief, despite the names.** Every campaign name reads `2026-Q2`, but delivery
started **2026-06-12** and is still running: **Q2 38,095 imps / $2,722.20, Q3 81,013 imps /
$4,714.45** (whole flight to 2026-08-12: **119,108 imps / 290 clicks / $7,436.65**; markets
IN 61,921 · AUNZ 30,609 · HKTW 11,496 · SGMYIDPHTH 10,560 · KR 4,522 - all five remap cleanly
through `PM_MARKET_REMAP`). Two thirds of it is Q3, so **never date-gate this lane to Q2** and don't
call it a Q2 campaign - the name is not the flight. The dashboard opens on Q3, so the lane's default
view is the Q3 portion; widen the range for the whole flight.

**Core DG's Q2 numbers MOVE.** Q2 spend / impressions / clicks / market rows / creatives all drop by
Surround ABM's delivery, because that is what "separate them" means. Q3 is unaffected (Surround ABM
never ran in Q3). The AI deck (`buildDeckPayload`) is pinned to `CORE_DG` explicitly - it is the Core
DG deliverable and is whole-flight, so it must not follow the lane selector.

**The status-dashboard accuracy checks are unaffected, by design.** `paid_media.rows[]` still carries
EVERY row - a `program` column was ADDED, nothing was removed - and the two TTD checks compare the
whole Snowflake advertiser total against the sum of `rows[]`. So the split is a rendering dimension,
not a data exclusion, and the monitor stays green with no mirrored edit. **Keep it that way:** if a
lane is ever implemented by dropping rows from the payload instead of tagging them, those checks go
red and the whole "advertiser-total vs dashboard-total catches a parsing regression" guarantee dies.

**What the Surround ABM lane deliberately does NOT show** (`PROGRAMS[].tabs` / `.plans` in
`dash/dashboard.html`, and the banner in `#laneNote` says so on screen):

- **Only the Paid Media tab.** Content Syndication / CS Comparison / QoQ / Internal Notes are
  CS-driven and are NOT program-scoped, so they would silently show Core DG's leads under a Surround
  ABM heading.
- **No budget pacing and no LinkedIn lead-commit block.** `PACING_PLANS` and `LI_LEADGEN_PLANS` are
  Core DG's committed plans; grading another brief's spend against them would be worse than showing
  nothing. `renderPacing` / `renderWeeklyTarget` / `liQ3PlanCtx` all gate on `laneCfg().plans`.
- The lane's footer row-count and window are **lane-scoped**, so it never advertises Core DG's flight
  over Surround ABM's numbers.

**Surround ABM has Content-Syndication campaigns too, and they are still in CORE.** The 4 P*
Salesforce ids labelled `CF Surround ABM *` in `definitions.json` (Q2-capped, see above) remain in
the core 13-ID CS filter exactly as before - this change touched the PAID model only. Moving them
would change the client's headline CS totals AND desync the status-dashboard CS checks, so it is a
separate, deliberate piece of work if they ever ask for it.

**To add another lane** (e.g. a future brief): one `WHEN` arm in the `PROGRAM` CASE in
`sql/03_stg_tradedesk.sql` (mirror it in `01_stg_linkedin.sql` - keep the two byte-identical), one
entry in `PROGRAMS` in `dash/dashboard.html`, one `<option>` in `#dashSelect`. Then reapply the views
and run the job with `FORCE_REBUILD=1` (a view change is invisible to the freshness gate). The job
prints a per-program `rows / imps / spend` line every run - that is the cheap check that the name
parse still works, and the thing to read first if a lane ever goes empty.

### Custom date range in the picker (2026-08-14)

The calendar always allowed an arbitrary range by clicking a start then an end day, but there was no
way to *type* a date and nothing in the preset list said "custom" - so a specific window (a flight, a
client's reporting fortnight) meant paging the calendar. Added, in `dash/dashboard.html` only:

- A **`Custom range`** preset, listed **last**. It is the "none of the above" state: it highlights
  automatically whenever the selection matches no preset, and clicking it does NOT change the range -
  it focuses the From field (overwriting a range you had just clicked out would be the wrong move).
  `detectPreset()` skips it explicitly, or `presetRange()`'s `else` arm would make it masquerade as
  "All time".
- **From / To date inputs** under the calendar (`#dpFrom` / `#dpTo`). They edit the SAME draft the
  calendar does, so the two always agree; `min`/`max` are bound to the data window, an out-of-window
  entry clamps, and a reversed pair is swapped rather than rejected. Bound to `change`, not `input` -
  a date input fires `input` on every partial keystroke and would clamp a half-typed year.
- Apply commits as normal, so the quarter derivation (`syncQuarterFromRange`), the `.qlbl` captions
  ("Quarter" for a custom span) and every tab re-render are unchanged.

### Lane dropdown: "Core DG APJ" + an EMEA placeholder (2026-08-05)

The topbar dropdown's first entry was renamed **"Core Demand Generation" → "Core DG APJ"** (client
request, JM) ahead of **Core DG EMEA** launching the week of 2026-08-05. The `<option>` **value is
still `core`** — only the label changed — so `switchDashboard()`, `activeTab`, every core-tab render
path and the whole payload are untouched by the rename. Two display strings follow it: the AI deck's
`context.campaign` in `buildDeckPayload()` and the Stage-A `business_model` brief in `dash/report.py`.
`campaign_key` stays `core_demand_gen` (the stable identifier `/report` summaries carry, so cached
decks don't orphan).

**Core DG EMEA sits in the dropdown DISABLED** — `<option value="core_emea" disabled>Core DG EMEA -
coming soon</option>`. It is a deliberate placeholder, not a wired lane: `switchDashboard()` sends any
non-`core` value to `renderCampaign()`, which would find no `COMBINED.campaigns.core_emea` and render
its empty *"No data / No delivery rows for this campaign group yet"* state — that reads as **broken**
rather than **pending**, so the option is greyed until there is real data behind it.

#### Adding Core DG EMEA

EMEA is a **second regional lane of the same programme**, not a single-campaign view, so it needs its
own model + payload branch rather than a `campaigns[]` entry:

1. **Data layer** — EMEA rows have to arrive in `raw_snowflake.*` (paid) and the Salesforce CS feed.
   Confirm the campaign-name/market tokens EMEA uses before writing any parse (APJ's markets are the
   7 APAC groups; EMEA will carry its own set) and add its CS campaign IDs to `definitions.json`.
2. **Model** — either add a `REGION` column through `paid_media_model` / `pacing_model` and split in
   the job, or clone the `sql/` chain per region. Prefer the column: one set of views, one gate.
3. **Payload** — emit an EMEA branch (e.g. `paid_media_emea` / `pacing_emea`, or a `region` key on
   the existing rows) from `job/main.py`, and extend the data-contract table below.
4. **Frontend** — drop `disabled`, then give `switchDashboard()` a branch that repoints the core
   panels at the EMEA payload (its `ALL_MARKETS`, targets and `PACING_PLANS` all differ from APJ's).
   `QUARTERS`/`activeChans()` need no change - both are region-agnostic.
5. Rebuild with `FORCE_REBUILD=1` (view/seed changes are invisible to the freshness gate) and
   redeploy the dash service.

### Quarter selection — opens on the CURRENT quarter, picked in the calendar (2026-08-05)

**The dashboard opens on the quarter today falls in — Q3 (Jul 1 – Sep 30) as of 2026-08-05** — and
the quarter is chosen **in the date-range calendar**, whose first two presets are `Q3 (Jul-Sep)` /
`Q2 (Apr-Jun)`. **The topbar Q2/Q3 chip pair is GONE** (client request 2026-08-05: a row of quarter
buttons doesn't scale as quarters accumulate) — one control, not two.

- `QUARTERS` (now declared **above** the `DateRange` IIFE) is the single source of truth for every
  quarter span, and the calendar's quarter presets are **generated from it** (`QUARTER_ORDER`,
  newest first) — the old duplicate hardcoded `q2`/`q3` preset dates are gone. **Add a quarter to
  `QUARTERS` and it appears in the calendar automatically**; nothing else to touch.
- The quarter presets are listed **first** deliberately: `detectPreset()` returns the first matching
  preset, so the picker button reads "Q3 (Jul-Sep)" instead of the identical-but-vaguer
  "This quarter" (both produce the same range while Q3 is current).
- The default comes from **`currentQuarterKey()`** (the quarter containing today, pinned to the
  nearest one outside the defined set), so it **rolls forward on its own** — no annual edit. It
  falls back to the full data window if that quarter has no data yet.
- The **date range stays the single source of truth**; the selected quarter is *derived* from it by
  **`syncQuarterFromRange()`** (was `syncQuarterChips`; `toggleQuarter`/`renderQuarterChips` were
  deleted with the chips). A custom calendar range resolves to **no** quarter and `qtrLabel()`
  captions read a neutral "Quarter". The **Q2+Q3 union** (`[Apr 1, dataMax]`, labelled "Q2-Q3") is
  still reachable by selecting a spanning range.
- The `.qtr-filter`/`.qtr-group`/`.qtr-chip` **CSS stays** — the Client/Admin view toggle reuses it.

**RIG drops out of the MARKETS filter under Q3** (client request 2026-07-09 — "remove the RIG filter
option when Q3 is toggled"): the Core DG Q3 plan carries **no RIG line**, so `visibleMarkets()` hides
the RIG chip AND excludes RIG from the data (`matchMarket` + the by-region grid) when Q3 is the active
quarter (Q3 selected, not Q2). RIG stays under Q2 and the Q2+Q3 union (both have RIG Q2 data). In
practice Q3 has zero RIG rows anyway, so this only removes an irrelevant chip — no headline number
changes. (The CS Comparison tab's A/B region dropdowns are NOT yet quarter-scoped, so they still list
RIG; low priority.)

**RIG is now Q3-hidden EVERYWHERE, not just the CS Overview (2026-08-05** — client: "RIG shouldn't be
detailed in the market focus for Q3"**)**: (1) the **Paid Media tab** got the same quarter gate —
`paidRigHidden()`/`paidVisibleMarkets()` mirror `visibleMarkets()`, so under a Q3-only selection the
RIG chip, its market-table/chart rows, its KPI contribution (`passesAll`) and its whole-flight
creative rows all drop out; `syncQuarterFromRange()` re-chips the paid tab too. This also killed the
phantom **$0.00 RIG row** the client saw under Q3: TTD's `ALL` token remaps to RIG and ~6 imps /
$0.002 of trailing post-Q2 `ALL` rows kept the row alive (`spendByMarket()` only drops EXACT-zero
markets). (2) the **QoQ tab's "Accepted leads by market" grid** drops the RIG row unconditionally
(that tab is Q3-vs-Q2 by construction; a RIG row read as a false collapse — Q2 74 leads vs a Q3 that
was never booked). RIG leads still count inside the QoQ status totals; only the market detail row is
gone. RIG still shows under Q2 / Q2-Q3 / custom ranges on the paid tab, and the deck payload stays
whole-flight all-markets (RIG's Q2 data belongs there). If a REAL `ALL`-market campaign ever runs in
Q3, un-gate `paidRigHidden()` and give it its own token — the data is only hidden, never discarded.

The selection is **global** — it drives Paid Media, Content Syndication and CS Comparison alike (the
QoQ tab is Q3-vs-Q2 by construction and ignores the range). Implemented entirely in
`dash/dashboard.html` (`QUARTERS`/`QUARTER_ORDER`/`quarterSpan`/`currentQuarterKey`/
`syncQuarterFromRange`/`visibleMarkets` + the generated quarter presets); no data-layer change.
**Because the default is now Q3, the RIG market chip is hidden on load** (see above) — expected, not
a bug.

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

### Budget pacing by channel (2026-07-20)

A **pacing section sits directly under the "Channel performance vs media plan benchmarks" table** on the
Paid Media tab - one horizontal bar per channel that ran in the **selected quarter** (it **follows
`selQuarters`**, itself derived from the calendar range). Each bar's **orange fill = billed spend within that quarter**, a
**dashed vertical marker = where spend should be today to finish the quarter on budget** (budget x fraction
of the quarter elapsed; a *complete* quarter pins the marker at 100%, so the bar reads as final delivery vs
budget), and the figure on the right is the **$ gap to pace** (behind / on / ahead). Frontend-only
(`renderPacing()` + the `.pace-*` CSS in `dash/dashboard.html`) - no data-contract or job change; it reads
the existing `paid_media.rows[]`. Re-renders on every quarter change (`applyDateRange → renderPaidMediaAll`).

- **Quarter-driven** (`PACING_PLANS` keyed by `Q2`/`Q3`; a custom calendar range that resolves to no
  quarter shows every quarter). **Q3** shows **TTD + LinkedIn** only (Reddit was dropped in Q3, LINE isn't a Q3 platform);
  **Q2** shows **all four** (TTD, LinkedIn, Reddit, LINE). "today" = the browser clock clamped to the
  flight. The section is deliberately **independent of the date-range picker and market chips**
  (whole-quarter, all-market) - filtering the dashboard does not move it.
- **Budgets are a hardcoded editable knob** `PACING_PLANS` in `dash/dashboard.html` (same pattern as
  mongodb's `MARGIN_TARGET` / the `CF1_CS_TARGET`); NOT in the pipeline - edit the const and redeploy the
  dash service (no job/view rebuild).
  - **Q3: TTD $47,624.56 / LinkedIn $61,022.44** - media-plan platform budgets from
    `targets/real_targets Q3.csv` ("Program total (APAC + JP)").
  - **Q2: every channel uses `useActual:true`** - Q2 has NO committed spend budget in the repo, so the
    budget IS the actual Q2 spend (each bar reads 100% delivered, $0 gap - a placeholder). Swap a channel's
    `useActual` for a `budget` number once the real Q2 figure is known, and its bar shows real over/under.
- **Multiplier-aware:** the budget is grossed by the same per-channel client-billed spend multiplier as
  spend (`bbMultFor`), so the pacing % is invariant to raw (direct) vs billed (front-door) access - it
  reconciles with the (also-grossed) spend column in the table above it.

### Paid Media shows only the channels that RAN in the selection (2026-08-05)

Client request alongside the Q3 default: **a channel with no activity in the selected period must not
appear at all** - Reddit and LINE are Q2-only, and under Q3 they were drawing empty zero rows,
zero-width donut slices and flat zero trend lines that read like under-delivery.

**`PM_CHANS` in `dash/dashboard.html` is now the ONE channel roster** (`key` / `label` / `long` /
`abbr` / `pill` / `color` / `pre` field-prefix / `mkey` market field / `rows()` accessor) and
**`activeChans()`** filters it to the channels with real delivery (spend **or** impressions **or**
clicks) inside the applied **date range** - so it follows the calendar, and a channel reappears the
moment a range covering its flight is selected. Everything channel-shaped renders from it:

| Piece | Behaviour |
|---|---|
| Spend KPI caption, blended spend/imps/clicks/CPM/CTR/CPC, "vs plan" CPC caption | live channels only (`renderPaidKPIs`) |
| "Spend by channel" donut + its hint line | one slice per live channel; hint reads e.g. "Trade Desk + LinkedIn mix." |
| "Daily spend - all channels stacked" | one stacked series per live channel |
| Daily efficiency trio (CTR / Clicks / CPC) | one line per live channel - was a hardcoded TTD/LinkedIn/Reddit trio, so **LINE now plots too under Q2** (`channelByGrain` gained the missing `ln_imp`/`ln_clk` sums) |
| "Channel performance vs media plan benchmarks" table | one row per live channel + an explicit empty-state row |
| "Market breakdown - …" heading, market stack / bar / table | heading names the live channels; stacked series + market totals sum only over them (`chanTotal`) |
| Creative channel filter + both creative tables | only live channels are offered and included; a pick that goes inactive falls back to "All channels" |
| TTD section (heading + "TTD daily" card) | hidden unless TTD delivered |
| LinkedIn funnel card | hidden unless LinkedIn delivered |
| Paid footer "Source: …" | lists the live channels |

**"LinkedIn leads vs weekly target" now hides outside its plan window.** `li_weekly`
(`sql/09_li_weekly_targets.sql`) is the **fixed 13-week Q2 plan** (Mar 30 - Jun 30), so the block
renders only while the selected range overlaps that window. This also fixes a real defect the Q3
default would have exposed: `weekIndex()` matched "any date >= the last week start", so **every
post-Q2 lead was piling into the W13 bar** - it now returns -1 outside `[planStart, planEnd]` (both
parsed from the plan's own `period` strings).

Market rows follow the same rule (`spendByMarket()` already dropped zero-spend markets). Frontend-only
- no `sql/`, `job/main.py` or data-contract change.

**Liveness keys on the DATE RANGE ONLY, deliberately not on the market chips.** If it also honoured
the chips, a channel whose markets all failed to parse would **vanish** from the tab instead of
showing a visible zero row - precisely the silent row-loss failure mode the [brief-number prefix
fix](#brief-number-campaign-prefixes-broke-paid-media-market-parsing-fixed-2026-08-04) chased down
(unmapped `MARKET_L3` passes the model's non-empty guard, then matches no chip, then `passesAll()`
drops it from every aggregate). A parsing regression must stay loud. It also keeps the channel list
stable while chips are toggled, instead of channels appearing/disappearing under the cursor.

### Q3 LinkedIn lead-gen commit plan - weekly pacing + benchmark "vs plan" lead columns (2026-08-06)

Client sheet (via JM): Q3 lead-gen is **LinkedIn only** and runs **only in 4 markets** -
ANZ $18,051 / CPL $301 / 60 leads, ASEAN $10,066 / $126 / 80, SAARC(India) $6,798 / $115 / 59,
GCR(HK) $2,858 / $260 / 11 = **$37,773 / 210 committed leads**. Frontend-only, all in
`dash/dashboard.html`:

- **`LI_LEADGEN_PLANS`** is the hardcoded editable knob (same pattern as `PACING_PLANS`); keys match
  the market chips (SAARC = India, GCR = HK). Edit it + redeploy the dash service to change the plan.
- **"LinkedIn leads vs weekly target" is now quarter-aware** (`renderWeeklyTarget` dispatches): a
  range touching Q3 renders the Q3 plan **paced FLAT by day** over Jul 1 - Sep 30 (`liPlanWeeks` -
  Monday-aligned weeks clamped to the quarter, so the partial first/last weeks get proportionally
  smaller targets and the cumulative target lands exactly on the commit); otherwise the fixed Q2
  `li_weekly` path renders unchanged. **Targets follow the market chips** (`liPlanScope`: all chips =
  210 total; one market selected = that market's commit), actuals follow chips + date range as
  before. The Q3 block **shows even with zero LinkedIn delivery** (a commit plan with no delivery
  must read behind, not vanish) - unlike the Q2 path, which still hides via `chanIsActive`.
- **The "Channel performance vs media plan benchmarks" table gained right-hand `Leads / vs plan /
  CPL / vs plan` columns** (LinkedIn row only; TTD has no pixel). Leads are graded against the
  **flat pace-to-date** (commit x fraction of Q3 elapsed, `liQ3PlanCtx`) with the whole-quarter
  commit in the bench note; CPL vs the blended planning CPL of the selected markets. Renders only
  under a **pure-Q3 selection** (a quarter commit can't grade Q2 or a custom sub-range - cells fall
  back to `-`). CAVEAT: actual CPL uses ALL LinkedIn spend (the feed has no campaign-objective
  split), so it reads conservative vs the lead-gen-line plan CPL - noted in the cell tooltip;
  splitting lead-gen campaigns out would need a `sql/` change.

## The data contract (`cloudflare.json` -> `/data.json`)

```json
{
  "last_updated": "YYYY-MM-DDTHH:MM:SSZ",
  "data_through": "YYYY-MM-DDTHH:MM:SSZ",
  "paid_media": {
    "row_count": 0,
    "window": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "days": 0 },
    "all_markets": ["ANZ","ASEAN","SAARC","RIG","KR","JP","GCR"],
    "rows": [ { "channel","program","date","week_start","market","imps","clicks","spend_usd",
                "leads","form_opens","link_clicks","action_clicks","video_starts",
                "video_completions","spend_jpy","fx_usd_jpy" } ],
    "creatives": [ { "channel","program","market","creative","imps","clicks","spend_usd","leads" } ],
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
  },
  "transmission": {
    "source_ids": [ { "id","campaign","leads","accepted","rejected","unprocessed","present" } ],
    "pacing": { "rows":[ {"market","tier","q2","q3","total"} ], "q2_total","q3_total","grand_total" }
  }
}
```

`transmission` (2026-07-10) powers the committed-data tables on the dev-only **"Internal Notes" tab**
(named "Data from Transmission" until 2026-08-05) - what Transmission
committed for this dashboard: `source_ids` = the canonical CS Source-ID list that should be present
(from `seed_cs_campaign_ids` / `definitions.json`) LEFT-JOINed to `salesforce_leads_live` so each ID
shows what has landed (+ a `present` flag); `pacing` = the target plan they sent (`targets_v2_norm` over
the committed `real_targets.csv`), per market x tier with a Q2/Q3 split. Built by
`build_transmission()` in `job/main.py`. See _Dev mode_ above.

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
