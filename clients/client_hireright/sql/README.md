# clients/client_hireright/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filter views first, then the roll-ups that read them). The export job
([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups to assemble `hireright.json`.

This is a **paid-media delivery baseline** — three platforms, reporting currency **USD**, no GA4/website
side. There are **no** `stg_google` / `stg_reddit` / `stg_salesforce` / `stg_ga4` views: HireRight has no
rows in Google Ads, Reddit or Salesforce, and its GA4 property can't be identified, so that data does not
exist for this client.

| File | View | What it does |
|---|---|---|
| `01_stg_dv360.sql` | `stg_dv360` | **DV360 filter** — `LOWER(ADVERTISER_NAME) LIKE '%hireright%'`. The only source with real geo: `COUNTRY_NAME` → `market` (friendly name where known, else raw 2-letter code). Spend in USD (AUD rows → USD @ `FX_AUD_USD = 0.65`; DV360 is already USD). |
| `02_stg_linkedin.sql` | `stg_linkedin` | **LinkedIn filter** — `LOWER(ACCOUNT_NAME) LIKE 'hireright%'`. `market = 'Global'` (audience NAM/EMEA/APAC combined, no usable geo). Account is `_USD` so spend is USD as-is (an `_AUD` account would convert @0.65). Carries the video + lead-gen fields for the funnel. |
| `03_stg_tradedesk.sql` | `stg_tradedesk` | **TradeDesk filter** — `ADVERTISER_NAME = 'HireRight'`. `imps = COALESCE(IMPRESSIONS, IMPRESSION)`. `market = 'Global'` (campaign names are persona/TAL, not geo). TradeDesk is AUD → spend converted to USD @0.65. |
| `04_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified ad-delivery base** — long-format union of the three platforms (platform · campaign · day · market · creative_type · imps · clicks · spend_usd · conversions). The single source for the campaign-grained roll-ups below. |
| `05_kpi.sql` | `kpi` | One-row headline totals + per-platform / blended sums + the reporting window (the data span across all platforms). Holds `fx_aud_usd = 0.65`. |
| `06_monthly.sql` | `monthly` | Per-month delivery — DV360 + TradeDesk + LinkedIn imps/clicks/spend (the hero trend). |
| `07_weekly.sql` | `weekly` | Per-ISO-week delivery (completeness + CSV export). |
| `08_ad_campaigns.sql` | `ad_campaigns` | **Campaign filter** option list + per-campaign totals (platform · campaign · imps · clicks · spend_usd · conversions · window), delivering campaigns only. |
| `09_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Ad delivery by campaign × month (Overview hero + Paid Media monthly). |
| `10_ad_campaign_weekly.sql` | `ad_campaign_weekly` | Ad delivery by campaign × ISO week (completeness + CSV). |
| `11_ad_campaign_market.sql` | `ad_campaign_market` | Ad delivery by campaign × market (**Market filter** + the by-market / by-country charts). |
| `12_li_creative.sql` | `li_creative` | LinkedIn by creative type (whole flight) with the full funnel metric set. |
| `13_li_campaign_creative.sql` | `li_campaign_creative` | LinkedIn by campaign × creative type (creative-mix donut + engagement funnel). |
| `14_li_campaigns.sql` | `li_campaigns` | LinkedIn by campaign (the detail table). |

The **Campaign filter** is the ad-delivery slicer: `stg_ad_delivery` (04) folds the three platforms into
one long-format fact, and `08–11` roll it up by campaign × {total, month, week, market}. The dashboard sums
the selected campaigns client-side to rescale every ad-delivery figure — selecting **all** campaigns (the
default) reproduces the whole-flight `kpi` / `monthly` totals exactly.

The **Market filter** scopes the market-grained views (`ad_campaign_market`) — i.e. the by-market /
by-country charts. DV360 carries real countries; TradeDesk + LinkedIn are `'Global'` air-cover, so the
Market filter primarily slices the DV360 geo. The platform totals, monthly trend, comparison table and
funnel are scoped by Platform + Campaign (market stays whole), the same way STT's ad totals were never
scoped by the GA4 Country filter.

**The filters + the FX constant are the only HireRight-specific bits.** The three source filters live once
in `stg_dv360` / `stg_linkedin` / `stg_tradedesk`; everything downstream reads those staging views. The FX
`0.65` is applied where each AUD source is staged and surfaced as `fx_aud_usd` in `05_kpi.sql`.

> **BigQuery note.** These run as BigQuery views (`create_views.py` uses `bigquery.Client`). BigQuery has
> no `ILIKE` and no `LIKE … ESCAPE`, so the brief's `ILIKE '%HireRight%'` / `ILIKE 'HireRight%'` are written
> as `LOWER(col) LIKE '…'`, and the LinkedIn `_AUD` guard as `ENDS_WITH(ACCOUNT_NAME, '_AUD')` (same intent,
> valid Standard SQL).

Apply:  `python clients/client_hireright/create_views.py`
