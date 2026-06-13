# client_cityperfume/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filters first, then the full-period roll-ups, then the year-on-year view, then the day-grained
roll-ups). The export job ([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups to assemble
`cityperfume.json`. Built on the [`client_STT`](../../client_STT/sql/README.md) pattern, plus a
first-party **Sales** family neither STT nor MongoDB had.

**Reporting currency = AUD — no FX.** Every source (Google `currency_code`, Meta `currency`,
TTD `currency`) is already AUD; GA4 and `v_sales` carry no currency column but the client is an AU
retailer, so AUD is assumed. There is **no `fx_*` constant** at the staging layer.

**Reporting window = `2025-01-01` → latest**, applied once in each `01–06 stg_*` view (the predicate
is `>= DATE '2025-01-01'`). Trends end at the last complete month; the current partial month is
labelled/excluded.

**`v_sales` is the source of truth** for revenue / orders / margin / AOV / customers. It is order-line
grained and carries `email` + `customer_id` (PII) — those columns **never leave BigQuery**. The
roll-ups read `06_stg_sales` (and one another), aggregate only, and the export job + a dashboard guard
keep identity keys out of the JSON.

## Staging filters (01–06) — the only client-specific bits
| File | View | Filter / role |
|---|---|---|
| `01_stg_google.sql` | `stg_google` | `raw_google_ads.perf_google_ads`, `account_name='City Perfume'`. `spend` is NUMERIC **AUD, not micros** (no `/1e6`). |
| `02_stg_meta.sql` | `stg_meta` | `raw_windsor.perf_meta`, `account_name='Cityperfume.com.au'`. Ad-grain (key `ad_id`); **all `effective_status`** kept (paused/archived hold ~50% of spend); creative_type derived `video` vs `image` from video metrics. |
| `03_stg_ttd.sql` | `stg_ttd` | `raw_windsor.perf_the_trade_desk`, `advertiser_name='City Perfume'`. Upper-funnel display only; parses `conversion_touch_03` from the double-encoded conversions JSON; no revenue. |
| `04_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified long base** — UNION of Google + Meta + TTD (platform · campaign · date · spend_aud · imps · clicks · platform_conversions · platform_revenue · creative_type). Every ad roll-up builds on this. |
| `05_stg_ga4.sql` | `stg_ga4` | `raw_ga4.perf_ga4`, `account_name='City Perfume'`. `session_default_channel_group` → bucket (**Cross-network = PMax = PAID**, not Other). |
| `06_stg_sales.sql` | `stg_sales` | `client_cityperfume.v_sales` (first-party truth): line-grain cleaned → `channel_group`, concentration `category`, `is_new_customer`. `customer_id`/`email` stay BQ-internal only. |

## Full-period roll-ups (the export job reads these as the exact source when the date range is **not** narrowed)
| Group | Files / views |
|---|---|
| Headline + trend | `10_kpi` (window consts, spend, revenue total+online, orders, margin, AOV, ROAS, platform-claimed separate) · `11_monthly` · `12_weekly` |
| GA4 / Website | `13_ga4_channels` · `14_ga4_monthly_channel` · `15_ga4_sources` · `16_ga4_funnel` |
| Sales (first-party) | `20_sales_kpi` · `21_sales_monthly` · `22_sales_products` (by revenue & by margin) · `23_sales_by_channel` · `24_sales_new_returning` · `25_sales_category` (EDP/EDT/Parfum/Gift Set & Hamper/Other) |
| Campaign / platform | `30_ad_campaigns` (filter option list + per-campaign totals) · `31_ad_campaign_monthly` · `32_ad_campaign_weekly` · `33_meta_creative` · `34_platform_summary` (platform-claimed ROAS shown separately) · `35_google_campaign_type` |
| Year-on-year | `40_yoy_monthly` — each month paired with the same calendar month a year earlier ($ + YoY%); powers the Year on Year tab. |

## Day-grained roll-ups (50–59) — the Date-range filter source
The dashboard's global **Date range** picker has DAY granularity, so these mirror the full-period
roll-ups at day grain. The dashboard clips them to the selected range, aggregates up for
KPIs/donuts/tables, and buckets to day/week/month for trends. When the range is not narrowed, the
full-period arrays above stay the exact source (so the default view is unchanged and distinct-customer
counts stay exact).

`50_sales_daily` · `51_sales_by_channel_daily` · `52_sales_category_daily` · `53_sales_products_daily`
· `54_ga4_channels_daily` · `55_ga4_sources_daily` · `56_ga4_funnel_daily` · `57_ad_campaign_daily`
· `58_google_campaign_type_daily` · `59_meta_creative_daily`.

## Invariant (mirror STT)
All-campaigns selection reproduces the whole-window ad totals exactly (verified: kpi = monthly = weekly
= ad_campaigns = platform_summary = **A$517,729**; sales views all = **A$16,053,034**). The sales side
has no campaign dimension, so it stays whole under the Campaign filter.

Apply:  `python client_cityperfume/create_views.py`  (or `./deploy_views_cityperfume.ps1`, which
re-applies then re-runs the export job). **Never edit views in the BigQuery console** — `sql/*.sql` is
the source of truth or they drift.
