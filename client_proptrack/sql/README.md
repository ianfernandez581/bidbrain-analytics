# client_proptrack/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filter views first, then the roll-ups that read them). The export job
([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups to assemble `proptrack.json`. Spend is **AUD**
throughout — there is no FX conversion anywhere.

| File | View | What it does |
|---|---|---|
| `01_stg_tradedesk.sql` | `stg_tradedesk` | **Trade Desk filter** — `tradedesk_apac_all`, `ADVERTISER_NAME = 'PopTrack'`. ⚠️ `imps = IMPRESSION` (singular; plural is NULL). Derives `segment` (AD_GROUP_NAME prefix stripped), `media_type`, `creative_size` (AD_TYPE), and the click / view-through conversion split. |
| `02_stg_linkedin.sql` | `stg_linkedin` | **LinkedIn filter** — `ACCOUNT_NAME = 'PropTrack_TransmissionSG_AUD'`. Native AUD (no ×1.34). Labels `creative_type`; carries `campaign_group`, engagements, video views, leads, lead-form opens. |
| `03_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified ad-delivery base** — long-format union of both platforms (platform · campaign · day · imps · clicks · spend_aud · conversions). The single source for the campaign-grained roll-ups. |
| `04_kpi.sql` | `kpi` | One-row headline metrics: combined window + per-platform windows, combined / Trade Desk / LinkedIn totals. |
| `05_monthly.sql` | `monthly` | Per-month Trade Desk + LinkedIn delivery (FULL OUTER JOIN, from 2025-08) — the Overview hero. |
| `06_td_media_type.sql` | `td_media_type` | Trade Desk Display vs Video. |
| `07_td_segments.sql` | `td_segments` | Trade Desk by ABM audience segment (spend desc). |
| `08_td_creative_sizes.sql` | `td_creative_sizes` | Trade Desk by creative size (AD_TYPE, imps desc). |
| `09_td_daily.sql` | `td_daily` | Trade Desk daily delivery (the burst series). |
| `10_li_groups.sql` | `li_groups` | LinkedIn by campaign group / objective (spend desc). |
| `11_li_creative.sql` | `li_creative` | LinkedIn by creative type (Standard vs Video). |
| `12_li_campaigns.sql` | `li_campaigns` | LinkedIn by campaign (spend desc) — the detail table. |
| `13_ad_campaigns.sql` | `ad_campaigns` | **Campaign filter** option list + per-campaign totals, delivering campaigns only. |
| `14_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Ad delivery by campaign × month (Overview hero rescale). |
| `15_ad_campaign_daily.sql` | `ad_campaign_daily` | Ad delivery by campaign × day (Trade Desk daily rescale). |

The **Campaign filter** (dashboard): `stg_ad_delivery` (03) folds the two platforms into one long-format
fact, and `13–15` roll it up by campaign × {total, month, day}. The dashboard sums the selected campaigns
client-side to rescale the **combined** ad-delivery figures (Overview + the Trade Desk daily) — selecting
**all** campaigns (the default) reproduces the whole-flight `kpi` / `monthly` totals exactly. The
per-platform breakdowns (`06–12`) have no campaign grain and stay whole-flight.

**The two filters + their column names are the only PropTrack-specific bits.** The Trade Desk
`ADVERTISER_NAME = 'PopTrack'` lives once in `stg_tradedesk`; the LinkedIn `ACCOUNT_NAME` lives once in
`stg_linkedin`; everything downstream reads those staging views.

Apply:  `python client_proptrack/create_views.py`
