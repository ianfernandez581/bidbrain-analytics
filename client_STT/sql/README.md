# client_STT/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filter views first, then the roll-ups that read them). The export job
([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups to assemble `stt.json`.

| File | View | What it does |
|---|---|---|
| `01_stg_ga4.sql` | `stg_ga4` | **GA4 filter** — Snowflake `google_analytics_apac_all`, `PROPERTY_ID = '318963196'` ("STT GDC Web All"). `market` = visitor `COUNTRY_NAME`; derives a coarse `channel_bucket` (Paid/Organic/Direct/Referral/Other). Event-grained source, so session/user metrics are taken from the per-session events only. |
| `02_stg_linkedin.sql` | `stg_linkedin` | **LinkedIn filter** — `ACCOUNT_ID IN ('515691430','511609128')` (SGD + USD accounts); the USD account's spend converted to SGD @1.34. |
| `03_stg_dv360.sql` | `stg_dv360` | **DV360 filter** — the Always On flight (`ADVERTISER_ID IN …`; two delivering campaigns, SGD). Maps `COUNTRY_NAME` → market; carries `campaign_name`. |
| `03b_stg_google.sql` | `stg_google` | **Google Ads filter** — `CAMPAIGN_NAME LIKE '%STT%'` (mixed USD/SGD → SGD @1.34). Market parsed from the campaign name. |
| `03c_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified ad-delivery base** — long-format union of the three platforms (platform · campaign · day · market · creative_type · imps · clicks · spend_sgd). The single source for the campaign-grained roll-ups below. |
| `18_google_markets.sql` | `google_markets` | Google Ads paid-search delivery by market. |
| `04_kpi.sql` | `kpi` | One-row headline metrics for the campaign window + prior-year baseline. Holds `FX_USD_SGD = 1.34`. |
| `05_monthly.sql` | `monthly` | Per-month GA4 (by bucket) + LinkedIn + DV360 — the hero trend (from 2025-01). |
| `09_li_creative.sql` | `li_creative` | LinkedIn by creative type. |
| `10_li_campaigns.sql` | `li_campaigns` | LinkedIn by campaign. |
| `11_dv_markets.sql` | `dv_markets` | DV360 by market (SGD spend). |
| `12_weekly.sql` | `weekly` | Per-ISO-week ad delivery vs Display+Social sessions — the Ads→Traffic correlation. |
| `13_ga4_kpi_market.sql` | `ga4_kpi_market` | GA4 headline metrics **by market** + prior-year baseline — powers the Country filter. |
| `14_ga4_monthly_market.sql` | `ga4_monthly_market` | GA4 monthly sessions **by market** (Country-filtered trends). |
| `15_ga4_weekly_market.sql` | `ga4_weekly_market` | GA4 weekly sessions **by market** (Country-filtered Ads→Traffic). |
| `16_ga4_channels_market.sql` | `ga4_channels_market` | GA4 sessions by channel **by market**. |
| `17_ga4_sources_market.sql` | `ga4_sources_market` | GA4 top source/medium **by market** (global top-60, re-ranked client-side). |
| `06_ga4_key_events.sql` | `ga4_key_events_market` | GA4 key events **by event type × month × market** — every configured key event (`KEY_EVENTS > 0`), read straight from the raw source since `stg_ga4` collapses them into one `conversions` total. Powers the Website tab's key-events breakdown. |
| `19_ad_campaigns.sql` | `ad_campaigns` | **Campaign filter** option list + per-campaign totals (platform · campaign · imps · clicks · spend_sgd · window), delivering campaigns only. |
| `20_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Ad delivery by campaign × month (Overview hero + Paid Media monthly). |
| `21_ad_campaign_weekly.sql` | `ad_campaign_weekly` | Ad delivery by campaign × ISO week (Ads → Traffic weekly + scatter). |
| `22_ad_campaign_market.sql` | `ad_campaign_market` | Ad delivery by campaign × market (Paid Media Google + DV360 by market). |
| `23_li_campaign_creative.sql` | `li_campaign_creative` | LinkedIn delivery by campaign × creative type (Paid Media creative mix). |

The **Country filter** (dashboard) is the GA4 `account_name` → `market` label, with "Global" deselected by
default. The `13–17` market-grained views ship the per-market GA4 data the dashboard sums over the
selected countries.

The **Campaign filter** is the ad-delivery analogue: `stg_ad_delivery` (03c) folds the three platforms into
one long-format fact, and `19–23` roll it up by campaign × {total, month, week, market, creative}. The
dashboard sums the selected campaigns client-side to rescale every ad-delivery figure — selecting **all**
campaigns (the default) reproduces the whole-flight `kpi` / `monthly` / `weekly` / market totals exactly.
The GA4/website side has no campaign dimension, so it is untouched by this filter.

**The filter + the FX/window constants are the only STT-specific bits.** The GA4 property lives once in
`stg_ga4`; the LinkedIn accounts, DV360 advertisers and Google Ads campaign filter live once in
`stg_linkedin` / `stg_dv360` / `stg_google`; everything downstream reads those staging views. The FX
`1.34` is applied where each USD source is staged (`02_stg_linkedin.sql`, `03_stg_dv360.sql`,
`03b_stg_google.sql`) and surfaced as the `fx_usd_sgd` constant in `04_kpi.sql`. To change the
campaign-window start (`DATE '2025-06-01'`), edit `04_kpi.sql`, `12_weekly.sql` and the GA4 market
views `13–17` / `21`.

Apply:  `python client_STT/create_views.py`
