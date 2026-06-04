# client_schneider/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the
`stg_*` filters first, then the unified base, then the roll-ups, then the seeds, then the GA4
layer). The export job ([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups + seeds to
assemble `schneider.json`. Built on the [`client_STT`](../../client_STT/sql/README.md) pattern.

**Reporting currency = AUD.** USD/SGD rows are converted at fixed FX constants set once in the
`stg_*` views and surfaced in `kpi`: **`FX_USD_AUD = 1.50`**, **`FX_SGD_AUD = 1.15`**
(placeholders — confirm with the client, then update every `stg_*` spend CASE + `kpi`).

**No `stg_google` / `stg_reddit` / `stg_salesforce`** — Schneider Electric has **no rows** in
`raw_snowflake.{google_ads_apac, reddit_ads_apac_all, salesforce_cs_apac_all}`. Search, Reddit
and CRM leads are surfaced on the dashboard as data-readiness stubs, not zero performance.

## Staging filters (the only SE-specific bits — filters resolved in the brief)
| File | View | Filter |
|---|---|---|
| `01_stg_dv360.sql` | `stg_dv360` | `ADVERTISER_NAME LIKE 'APAC \| Schneider Electric%'`. spend→AUD from `CURRENCY`. market = COUNTRY_NAME → fine geography (AU/NZ/India/… kept; global spill grouped to regions). |
| `02_stg_linkedin.sql` | `stg_linkedin` | `ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'` (3 accts: `_USD`/`_AUD`/`_SGD`). No currency column → spend→AUD inferred from the account suffix. market parsed from `CAMPAIGN_NAME`. |
| `03_stg_tradedesk.sql` | `stg_tradedesk` | `ADVERTISER_NAME = 'Schneider Electric'`. `imps = COALESCE(IMPRESSIONS, IMPRESSION)`. spend→AUD from `CURRENCY` (all AUD today). market parsed from `CAMPAIGN_NAME` (same parser as LinkedIn). |
| `04_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified base** — long-format UNION of the three platforms (platform · campaign · day · market · channel_objective(NULL) · creative_type(LI only) · imps · clicks · spend_aud). Every campaign-grained roll-up builds on this. |

## Headline + campaign roll-ups
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

## Seeds (the human bridge + plan data — `UNNEST([STRUCT(...)])`, editable in-repo, **TODO**)
| File | View | What it holds |
|---|---|---|
| `30_seed_campaign_map.sql` | `seed_campaign_map` | internal campaign → display / objective / KPI / region + **`match_pattern`** (the `\|`-separated CONTAINS bridge to platform `CAMPAIGN_NAME`). Unmatched delivery → `(unmapped)`. |
| `31_seed_plan_budget.sql` | `seed_plan_budget` | budget_aud · budget_basis (incl/ex fees) · flight_start/end (NULL → delivery window). |
| `32_seed_plan_flighting.sql` | `seed_plan_flighting` | period (YYYY-MM) × weight_pct — pacing-vs-plan. |
| `33_seed_targets.sql` | `seed_targets` | kpi × target_value (nullable) — KPI-vs-target progress. |
| `34_seed_channel_split.sql` | `seed_channel_split` | the approved 2306 (ai_lc) channel split only (= 480,600 AUD). |

## GA4 (Website tab) — **SHIPPED DISABLED**
`40_stg_ga4` + `41–46 ga4_*_market` are copied from STT with the property filter parameterised
to a placeholder (`PROPERTY_ID IN ('REPLACE_WITH_SE_GA4_PROPERTY_IDS')`) → the views apply
cleanly but return **0 rows**. The job gates the `ga4_*` JSON behind `GA4_ENABLED` (default
`False`) and the dashboard shows the "awaiting GA4 property id" stub. **To enable:** set the real
property id(s) in `40_stg_ga4.sql` (and `46_…`), flip `GA4_ENABLED = True` in `job/main.py`,
reapply views + re-run the job.

Apply:  `python client_schneider/create_views.py`
