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
| `00_fx.sql` | `fx` | **The ONE FX constant** (`aud_usd = 0.65`). Every AUD->USD conversion CROSS JOINs this single row and `05_kpi` reads the *printed* rate from it too, so the rate shown to the client can never drift from the rate the spend was converted at (it used to be the literal `0.65` typed out in four files). The value is an **unconfirmed placeholder** - see the file header. |
| `01_stg_dv360.sql` | `stg_dv360` | **DV360 filter** - `LOWER(ADVERTISER_NAME) LIKE '%hireright%'`. The only source with real geo: `COUNTRY_NAME` -> a full ISO country `market` **plus a `region` rollup**. Campaign name is **normalised** (brief-number prefix stripped into its own `brief` column - names are not stable keys). Conversions carried as `attr_conv` (Floodlight, post-click + post-view). Spend in USD via the `fx` view. |
| `02_stg_linkedin.sql` | `stg_linkedin` | **LinkedIn filter** (campaign name normalised; `leads` kept as its own measure) — `LOWER(ACCOUNT_NAME) LIKE 'hireright%'`. `market = 'Global'` (audience NAM/EMEA/APAC combined, no usable geo). Account is `_USD` so spend is USD as-is (an `_AUD` account would convert @0.65). Carries the video + lead-gen fields for the funnel. |
| `03_stg_tradedesk.sql` | `stg_tradedesk` | **TradeDesk filter** (campaign name normalised; conversions carried as `attr_conv`) — `ADVERTISER_NAME = 'HireRight'`. `imps = COALESCE(IMPRESSIONS, IMPRESSION)`. `market = 'Global'` (campaign names are persona/TAL, not geo). TradeDesk is AUD → spend converted to USD @0.65. |
| `04_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified ad-delivery base** - long-format union of the three platforms (platform - campaign - brief - day - market - region - creative_type - imps - clicks - spend_usd - engagements - **leads** - **attr_conv**). **There is deliberately no single `conversions` column**: it used to sum DV360 Floodlight + TTD click+view + LinkedIn LEADS into one figure, which added post-view display conversions to submitted lead forms. Read the header before re-merging them. |
| `05_kpi.sql` | `kpi` | One-row headline totals + per-platform / blended sums + the reporting window. `ad_conv` is **gone**, replaced by `li_leads` (LinkedIn lead forms) and `ad_attr_conv` (DV360 + TTD attributed, not de-duplicated). `fx_aud_usd` is read from the `fx` view. |
| `06_monthly.sql` | `monthly` | Per-month delivery — DV360 + TradeDesk + LinkedIn imps/clicks/spend (the hero trend). |
| `07_weekly.sql` | `weekly` | Per-ISO-week delivery (completeness + CSV export). |
| `08_ad_campaigns.sql` | `ad_campaigns` | **Campaign filter** option list + per-campaign totals (platform · campaign · imps · clicks · spend_usd - engagements - leads - attr_conv - window), delivering campaigns only. |
| `09_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Ad delivery by campaign × month (Overview hero + Paid Media monthly). |
| `10_ad_campaign_weekly.sql` | `ad_campaign_weekly` | Ad delivery by campaign × ISO week (completeness + CSV). |
| `11_ad_campaign_market.sql` | `ad_campaign_market` | Ad delivery by campaign × market (**Market filter** + the by-market / by-country charts). Carries `region` for the region rollup chart. |
| `12_li_creative.sql` | `li_creative` | LinkedIn by creative type (whole flight) with the full funnel metric set. |
| `13_li_campaign_creative.sql` | `li_campaign_creative` | LinkedIn by campaign × creative type (creative-mix donut + engagement funnel). |
| `14_li_campaigns.sql` | `li_campaigns` | LinkedIn by campaign (the detail table). |
| `15_daily.sql` | `daily` | Per-day delivery — DV360 + TradeDesk + LinkedIn imps/clicks/spend. Powers the **Day** grain of the two trend charts; mirrors `monthly`/`weekly` (day key = ISO `'YYYY-MM-DD'` string). |
| `16_ad_campaign_daily.sql` | `ad_campaign_daily` | Ad delivery by campaign × day (the **Day** grain of the Overview hero + Paid Media trend chart). Mirrors `ad_campaign_monthly`/`ad_campaign_weekly`. |
| `17_scope_audit.sql` | `scope_audit` | **Scope audit.** Two of the three source filters are substring/prefix matches on a human-typed name, so a second HireRight advertiser or a renamed account would silently join every KPI (numbers go UP, which reads as performance, not as a bug). Lists every matched entity with its volume, window and currency form. The job logs it each run and WARNs when a source matches more than one entity. |
| `18_targets.sql` | `targets` | Thin view over the committed-CSV seed `seed_media_plan` (`targets/media_plan.csv` -> `seed_static.py`). **Every target column is NULLABLE and NULL means "not committed in the plan"**, which is not a target of zero. |
| `19_pacing.sql` | `pacing` | Planned vs delivered per platform, with BOTH attainment (`*_pct`, of the whole commitment) and **pace to date** (`*_pace`, against the even flight pace so far). Carries `has_targets` - FALSE today, which makes the dashboard hide its pacing section entirely rather than draw 0/0 cards. |

The **Campaign filter** is the ad-delivery slicer: `stg_ad_delivery` (04) folds the three platforms into
one long-format fact, and `08–11` + `16` roll it up by campaign × {total, month, week, market, day}. The two
trend charts (Overview hero + Paid Media) carry a **VIEW BY** Month/Week/Day grain toggle that re-aggregates
from `ad_campaign_monthly` / `ad_campaign_weekly` / `ad_campaign_daily`, plus an **AXIS** Relative/Absolute
scale toggle (default Relative: the clicks line is indexed to its own peak=100). The dashboard sums
the selected campaigns client-side to rescale every ad-delivery figure — selecting **all** campaigns (the
default) reproduces the whole-flight `kpi` / `monthly` totals exactly.

The **Market filter** scopes the market-grained views (`ad_campaign_market`) — i.e. the by-market /
by-country charts. DV360 carries real countries; TradeDesk + LinkedIn are `'Global'` air-cover, so the
Market filter primarily slices the DV360 geo. The platform totals, monthly trend, comparison table and
funnel are scoped by Platform + Campaign (market stays whole), the same way STT's ad totals were never
scoped by the GA4 Country filter.

**The filters + the FX constant are the only HireRight-specific bits.** The three source filters live once
in `stg_dv360` / `stg_linkedin` / `stg_tradedesk`; everything downstream reads those staging views. The FX
rate lives once in **`00_fx.sql`** — every AUD source CROSS JOINs it, and `05_kpi.sql` reads the value it
*surfaces* as `fx_aud_usd` from the same row. Previously the literal `0.65` was typed into four separate
files, so editing three and missing the fourth would have left the dashboard printing one rate while the
spend column was converted at another — a wrong number that looks perfectly self-consistent.

## Two rules this client's views now enforce

**1. Outcomes are never blended.** `04_stg_ad_delivery` carries `leads` (LinkedIn lead-gen form
submissions) and `attr_conv` (DV360 + TradeDesk post-click **and post-view** attributed conversions) as
two separate measures. They used to be summed into one `conversions` column surfaced as a headline
"Conversions" tile captioned *"DV360 + TradeDesk + LinkedIn leads"*. A view-through display conversion is
not a lead, the two programmatic tags are not de-duplicated against each other, and the resulting figure
read as an outcome count while being mostly unclicked impressions. The full reasoning is in that file's
header — do not re-merge them without a conversion definition agreed with the client.

**2. Campaign names are normalised.** Every `stg_*` view strips a leading brief-number prefix
(`REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '')`) and keeps the number in its own `brief` column.
Transmission is progressively prefixing campaign names across the estate (see `md/AGENTS.md` → "Campaign
names are NOT stable keys"); without this, the day a HireRight campaign gets prefixed it would appear in
the feed under **two** names and every per-campaign aggregate would split in half.

> **BigQuery note.** These run as BigQuery views (`create_views.py` uses `bigquery.Client`). BigQuery has
> no `ILIKE` and no `LIKE … ESCAPE`, so the brief's `ILIKE '%HireRight%'` / `ILIKE 'HireRight%'` are written
> as `LOWER(col) LIKE '…'`, and the LinkedIn `_AUD` guard as `ENDS_WITH(ACCOUNT_NAME, '_AUD')` (same intent,
> valid Standard SQL).

Apply:  `python clients/client_hireright/create_views.py`
