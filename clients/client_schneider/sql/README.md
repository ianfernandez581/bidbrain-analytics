# clients/client_schneider/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the
`stg_*` filters first, then the unified base + roll-ups (05–16), the **Content-Syndication + paid-tagged
views** (17–20, which read `seed_salesforce_map` / `seed_campaign_map`), then the GA4 layer (40–46,
**unused by the clone** but still applied). The `seed_*` **tables** are loaded SEPARATELY from
`../data/*.csv` by [`../load_seeds.py`](../load_seeds.py) — they are no longer views, so `create_views.py`
does not create them and **`load_seeds.py` must run first**. The export job ([`../job/main.py`](../job/main.py))
`SELECT`s `cs_by_programme` (18) + `cs_weekly` (19) + `pm_delivery` (20) + the seed tables to assemble
the **3-tab mongodb-clone** `schneider.json`. (Views 05–16 are the legacy paid-media roll-ups — kept,
but the clone reads `pm_delivery` instead.) Modelled on [`client_mongodb`](../../client_mongodb/).

**Reporting currency = AUD.** USD/SGD rows are converted at fixed FX constants set once in the
`stg_*` views and surfaced in `kpi`: **`FX_USD_AUD = 1.50`**, **`FX_SGD_AUD = 1.15`**
(placeholders — confirm with the client, then update every `stg_*` spend CASE + `kpi`).

**No `stg_google` / `stg_reddit`** — Schneider has **no rows** in `raw_snowflake.{google_ads_apac,
reddit_ads_apac_all}`; Search & Reddit are surfaced as data-readiness stubs, not zero performance.
**`stg_salesforce` IS now wired** (see below): Schneider DOES have leads in
`raw_snowflake.salesforce_cs_apac_all` — **95 in-flight leads** (`eba` 42, `water_env` 28, `heavy` 25),
joined to internal campaigns via `seed_salesforce_map`. Leads are **clamped to each program's flight
window** (the same `seed_plan_budget` flight the Gantt shows) — pre-flight spillover is excluded (e.g.
EBA had 4 leads before its 2026-05-25 start). (This corrects the old "no rows in salesforce_cs_apac_all" claim.)

## Staging filters (the only SE-specific bits — filters resolved in the brief)
| File | View | Filter |
|---|---|---|
| `01_stg_dv360.sql` | `stg_dv360` | `ADVERTISER_NAME LIKE 'APAC \| Schneider Electric%'`. spend→AUD from `CURRENCY`. market = COUNTRY_NAME → fine geography (AU/NZ/India/… kept; global spill grouped to regions). |
| `02_stg_linkedin.sql` | `stg_linkedin` | `ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'` (3 accts: `_USD`/`_AUD`/`_SGD`). No currency column → spend→AUD inferred from the account suffix. market parsed from `CAMPAIGN_NAME`. |
| `03_stg_tradedesk.sql` | `stg_tradedesk` | `ADVERTISER_NAME = 'Schneider Electric'`. `imps = COALESCE(IMPRESSIONS, IMPRESSION)`. spend→AUD from `CURRENCY` (all AUD today). market parsed from **`AD_GROUP_NAME` first, then `CAMPAIGN_NAME`** — ANZ-level campaigns (EBA, AirSeT) carry the AU/NZ country only in the ad-group name (`..._Australia_...`/`..._NewZealand_...`, `..._AU_...`/`..._NZ_...`); the campaign-name-only parse used to strand that delivery (all of EBA's TTD) in `Unmapped`. |
| `04_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified base** — long-format UNION of the three platforms (platform · campaign · day · market · channel_objective(NULL) · creative_type(LI only) · imps · clicks · spend_aud). Every campaign-grained roll-up builds on this. |

## Headline + campaign roll-ups (05–16) — **LEGACY, applied but unused by the clone**
> These powered the old 6-tab paid-media dashboard. The mongodb clone reads `pm_delivery` (20) instead;
> they're kept (cheap, and a fallback) but the job no longer SELECTs them. The "Powers …" notes below
> describe the *old* tabs.

| File | View | What it does |
|---|---|---|
| `05_kpi.sql` | `kpi` | One-row whole-flight media headline (per-platform + blended `ad_*`), the FX constants, and per-platform delivery windows. |
| `06_monthly.sql` | `monthly` | Media delivery by month (per-platform + blended). Spend trend + pacing. |
| `07_weekly.sql` | `weekly` | Media delivery by ISO week (per-platform + blended). Weekly pacing / flight overlap. |
| `08_ad_campaigns.sql` | `ad_campaigns` | Campaign filter option list + per-campaign totals (delivering only, outer WHERE). |
| `09_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Delivery by campaign × month. |
| `10_ad_campaign_weekly.sql` | `ad_campaign_weekly` | Delivery by campaign × ISO week. |
| `11_ad_campaign_market.sql` | `ad_campaign_market` | Delivery by campaign × market (all three platforms; powers Geography + AU/NZ split). |
| `12_ad_campaign_metrics.sql` | `ad_campaign_metrics` | Campaign-grained FUNNEL metrics (conversions / video starts+completions / leads / engagements / viewable) folded across platforms. Powers Delivery & Funnel. |
| `13_li_creative.sql` | `li_creative` | LinkedIn by creative type (whole flight). |
| `14_li_campaign_creative.sql` | `li_campaign_creative` | LinkedIn by campaign × creative type (Campaign-filtered creative mix). |
| `15_daily.sql` | `daily` | Media delivery by day (per-platform + blended) — Day grain for the trend charts. |
| `16_ad_campaign_daily.sql` | `ad_campaign_daily` | Delivery by campaign × day. |

## Content Syndication + paid-delivery views (17–20) — the mongodb-clone data layer
Scoped to the 5 lead-gen programs. These four power the 3-tab dashboard.
| File | View | What it does |
|---|---|---|
| `17_stg_salesforce.sql` | `stg_salesforce` | Filters `raw_snowflake.salesforce_cs_apac_all` to SE's 9 SF campaigns by INNER JOINing `seed_salesforce_map` on `CAMPAIGN_ID`; attaches **campaign** (internal id), **programme** (`pillar_label`), **market** (normalized `COUNTRY_NAME` → Australia/New Zealand/Other) + a forward-compatible `status_bucket` (buckets on `LEAD_STATUS` only — `STATUS`/`LEAD_STATUS_SF` are INT64/all-NULL; every lead is `New` today). **CLAMPS leads to the program's flight window** (LEFT JOIN `seed_plan_budget`: `DAY >= flight_start` and `<= flight_end`) so pre-flight spillover isn't counted. |
| `18_cs_by_programme.sql` | `cs_by_programme` | leads per campaign × programme × market × status + last lead day — the CS snapshot, by-market/by-programme doughnuts, by-market summary, programme×market table. |
| `19_cs_weekly.sql` | `cs_weekly` | leads per campaign × programme × market × ISO week — the Weekly-pacing chart (real dated weekly actuals; unlike mongodb, which ramps undated leads). |
| `20_pm_delivery.sql` | `pm_delivery` | paid delivery (DV360/TTD/LinkedIn) TAGGED to its program via the `match_pattern` join (first-match-wins by `seq`, replicating the dashboard's old client-side `idOf`), at program × day × market × platform grain, **scoped to the 5 programs**. Market folded to **{Australia, New Zealand}** only (`stg_tradedesk`/`stg_dv360` already resolve most AU/NZ; a tiny unsplittable combined-ANZ residual → Australia). No ANZ/Other bucket. |

## Seeds (the human bridge + plan data — now CSV-loaded TABLES, not views)
The seeds moved OUT of the old `sql/30–34` STRUCT-literal views into version-controlled CSVs under
[`../data/`](../data/), loaded into BigQuery `seed_*` **tables** by [`../load_seeds.py`](../load_seeds.py)
(`data/<stem>.csv` → `client_schneider.seed_<…>`, read-as-text → coerce → WRITE_TRUNCATE; it auto-drops
any pre-existing seed_* VIEW on the first run). **`load_seeds.py` must run BEFORE `create_views.py`**
(`stg_salesforce` reads `seed_salesforce_map`). Edit the CSV, re-run the loader. The `match_pattern`
first-match-wins precedence is preserved by an explicit **`seq`** column (0-based row order) in
`campaign_map.csv`, which `20_pm_delivery`'s SQL join consumes (`ORDER BY seq`, `rn=1`).

| CSV (`data/`) | Table | What it holds |
|---|---|---|
| `campaign_map.csv` | `seed_campaign_map` | internal campaign → display / objective / KPI / region + **`match_pattern`** (CONTAINS bridge) + `portfolio` + **`seq`** (precedence). 28 rows (adds `nel`). |
| `plan_budget.csv` | `seed_plan_budget` | budget_aud · budget_basis (incl/ex fees) · flight_start/end. |
| `plan_flighting.csv` | `seed_plan_flighting` | period × weight_pct — pacing-vs-plan. |
| `targets.csv` | `seed_targets` | kpi × target_value — program-level outcome targets (EcoConsult). |
| `channel_split.csv` | `seed_channel_split` | the approved 2306 (ai_lc) channel split only (= 480,600 AUD). |
| `media_plan.csv` | `seed_media_plan` | **NEW** — the digested media plan: per program × channel × line_type, with imp/reach/click targets (delivery lines) and `lead_target` + `sf_campaign_id` (lead lines). Powers the Leads-tab targets + the Portfolio target-vs-actual. 25 rows. |
| `salesforce_map.csv` | `seed_salesforce_map` | **NEW** — Salesforce campaign id → internal id + pillar_label (the lead join). 9 rows. |

## GA4 (Website tab) — **SHIPPED DISABLED**
`40_stg_ga4` + `41–46 ga4_*_market` are copied from STT with the property filter parameterised
to a placeholder (`PROPERTY_ID IN ('REPLACE_WITH_SE_GA4_PROPERTY_IDS')`) → the views apply
cleanly but return **0 rows**. The job gates the `ga4_*` JSON behind `GA4_ENABLED` (default
`False`) and the dashboard shows the "awaiting GA4 property id" stub. **To enable:** set the real
property id(s) in `40_stg_ga4.sql` (and `46_…`), flip `GA4_ENABLED = True` in `job/main.py`,
reapply views + re-run the job.

Apply (order matters): `python clients/client_schneider/load_seeds.py` (seed tables) **then**
`python clients/client_schneider/create_views.py` (views). The deploy scripts
([`deploy_views_schneider.ps1`](deploy_views_schneider.ps1), [`../deploy_seeds_schneider.ps1`](../deploy_seeds_schneider.ps1))
do this in the right order for you.
