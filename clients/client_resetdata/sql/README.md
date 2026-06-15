# clients/client_resetdata/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file in the `client_resetdata` dataset, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filter views **01–06** — including **04b_stg_reddit**, which sorts after `04_stg_ttd` and before
`06_stg_ad_delivery` that reads it — first, then the **07–23** roll-ups that read them). The export job
([`../job/main.py`](../job/README.md)) `SELECT`s the roll-ups to assemble `resetdata.json`.

ResetData is **B2B** ("ads → website traffic / leads"): there is **no revenue / ROAS / transactions**
(those are ~0 upstream). Reporting currency is **AUD** throughout. The six sources read straight from
**three shared raw layers** — `raw_google_ads`, `raw_windsor`, `raw_ga4`.

| File | View | What it does |
|---|---|---|
| `01_stg_ga4.sql` | `stg_ga4` | **GA4 filter** — `raw_ga4.perf_ga4`, `client_slug = 'reset-data'`. Already Traffic-Acquisition grain, so a plain filter + a coarse `channel_bucket` CASE (Paid/Organic/Direct/Referral/Other). AU-only (no market/country dimension). `conversions` = GA4 key events. |
| `02_stg_google.sql` | `stg_google` | **Google Ads filter** — native DTS table `raw_google_ads.perf_google_ads`, `account_name = 'Reset Data'`. `spend` is **already whole AUD** (DTS converted micros — do NOT divide by 1e6). Carries platform-reported `conversions` (the most reliable of the three). |
| `03_stg_meta.sql` | `stg_meta` | **Meta filter** — `raw_windsor.perf_meta`, `account_name = 'Reset backup – Ad account'` (**EN-DASH** `–`). `cost` already AUD. `leads` → `conversions` (sparse, B2B). Builds `creative_name` for the creative-mix view. |
| `04_stg_ttd.sql` | `stg_ttd` | **The Trade Desk filter** — `raw_windsor.perf_the_trade_desk`, `advertiser_name = 'ResetData'`. Bills **USD → AUD ×1.50** (`FX_USD_AUD`, same constant as `client_schneider`). `conversions` is NULL upstream → none emitted. `ad_format` = creative size. |
| `04b_stg_reddit.sql` | `stg_reddit` | **Reddit filter** — `raw_windsor.perf_reddit`, `client_slug = 'resetdata'`. AUD native (no FX). `conversions` = sign-up + lead clicks (sparse); `page_visits` = page-visit clicks + views (traffic signal); carries `objective`. Native engagement / video metrics are NULL upstream; `reach` is non-additive so not summed. |
| `05_stg_ga4_events.sql` | `stg_ga4_events` | **GA4 key-events filter** — `raw_ga4.perf_ga4_events`, `client_slug = 'reset-data'`. Per-`event_name` split (vs `stg_ga4`'s single collapsed `conversions`), carrying `is_conversion_event`. |
| `06_stg_ad_delivery.sql` | `stg_ad_delivery` | **Unified ad-delivery base** — long-format `UNION ALL` of Google + Meta + TTD + Reddit (platform · campaign · day · creative · imps · clicks · spend_aud · conversions), all spend in AUD. The single source for the campaign-grained roll-ups below. |
| `07_kpi.sql` | `kpi` | One-row headline metrics for the window (`DATE '2025-12-01'` → latest GA4 day). Holds `fx_usd_aud = 1.50`. GA4 outcomes + Google/Meta/TTD/Reddit delivery; `ad_*` = the four platforms combined; `ad_conv` = Google + Meta + Reddit (TTD reports none). |
| `08_monthly.sql` | `monthly` | Per-month GA4 (sessions by bucket + mapped paid channels + key events) alongside Google/Meta/TTD/Reddit delivery — the Overview hero trend (from 2025-12). |
| `09_weekly.sql` | `weekly` | Per-ISO-week (Mon-anchored) ad delivery vs the mapped channel sessions (Paid Search/Social/Display) — the Ads → Traffic correlation series. |
| `10_ga4_channels.sql` | `ga4_channels` | GA4 sessions / engaged / users / key events by channel group — the channel-mix donut + Website-tab breakdown. |
| `11_ga4_key_events.sql` | `ga4_key_events` | GA4 key events by `event_name` × month (drops the high-volume pageview-class events), with `is_conversion_event` — the Website tab's key-events breakdown. |
| `12_ga4_sources.sql` | `ga4_sources` | Top 25 GA4 source/medium by sessions, ad platforms flagged `is_ad` (google/cpc, meta/ig/facebook, tradedesk/ttd/adsrvr). |
| `13_google_campaigns.sql` | `google_campaigns` | Google Ads delivery by campaign (whole flight) + platform conversions. Delivering rows only. |
| `14_meta_campaigns.sql` | `meta_campaigns` | Meta delivery by campaign (+ link_clicks / landing_page_views / leads). Delivering rows only. |
| `15_ttd_campaigns.sql` | `ttd_campaigns` | TTD delivery by campaign (AUD; no conversions). Delivering rows only. |
| `16_meta_creative.sql` | `meta_creative` | Meta delivery by creative (`creative_name`) — the creative-mix chart. |
| `17_ad_campaigns.sql` | `ad_campaigns` | **Campaign filter** option list + per-campaign totals (platform · campaign · imps · clicks · spend_aud · conversions · window), ordered by spend. Built on `stg_ad_delivery`. |
| `18_ad_campaign_monthly.sql` | `ad_campaign_monthly` | Ad delivery by campaign × month (Overview hero + Paid Media monthly, Campaign-filtered). Month key matches `monthly`. |
| `19_ad_campaign_weekly.sql` | `ad_campaign_weekly` | Ad delivery by campaign × ISO week (Ads → Traffic weekly + scatter, Campaign-filtered). Week-anchored to match `weekly`, from 2025-12-01. |
| `20_reddit_campaigns.sql` | `reddit_campaigns` | Reddit delivery by campaign (whole flight) + `objective` · `page_visits` · sign-up/lead `conversions` — the Paid Media **Reddit deep-dive** table. Delivering rows only. |
| `21_daily.sql` | `daily` | **Day-grain** analogue of `monthly` (keyed on `day` = 'YYYY-MM-DD'), powering the "View by → Day" toggle on the Overview hero / Website / Ads→Traffic trend charts. `raw_ga4.perf_ga4` is day-grained, so this is real per-day data. From 2025-12-01. |
| `22_ad_campaign_daily.sql` | `ad_campaign_daily` | **Day-grain** analogue of `ad_campaign_weekly` (campaign × `day`, carries `conversions`) for the Campaign-filtered Day grain. From 2025-12-01. Delivering rows only. |
| `23_ga4_key_events_daily.sql` | `ga4_key_events_daily` | **Day-grain** analogue of `ga4_key_events` (event_name × `day`) so the Overview key-events breakdown supports Day; Week grain is bucketed client-side from this feed. |

The **Platform filter** (dashboard) scopes ad-delivery figures to Google / Meta / TTD / Reddit, recomputed
client-side from the per-platform columns. The **Campaign filter** is the ad-delivery analogue:
`stg_ad_delivery` (06) folds the four platforms into one long-format fact, and `17–19` roll it up by
campaign × {total, month, week}. The dashboard sums the selected campaigns client-side to rescale every
ad-delivery figure — selecting **all** campaigns (the default) reproduces the whole-flight `kpi` /
`monthly` / `weekly` totals exactly. The GA4 / website side has **no campaign dimension**, so it is
untouched by either filter. There is **no Country filter** (AU-only).

**The per-table filter + the FX/window constants are the only ResetData-specific bits.** Each source's
filter lives once in its `stg_*` view (Google `account_name`, Meta `account_name` with the en-dash, TTD
`advertiser_name`, GA4 `client_slug`); everything downstream reads those staging views. The FX `1.50` is
applied where TTD's USD spend is staged (`04_stg_ttd.sql`) and surfaced as `fx_usd_aud` in `07_kpi.sql`.
To change the window start (`DATE '2025-12-01'`), edit `07_kpi.sql`, `08_monthly.sql`, `09_weekly.sql`
and `19_ad_campaign_weekly.sql`.

> **Slug split:** Google Ads + GA4 tag the client `reset-data` (hyphen); Meta + TTD tag it `resetdata`
> (no hyphen). Each `stg_*` view therefore filters by the **stable per-table key** (account / advertiser
> name) above, not a single shared slug.

Apply: `.\.venv\Scripts\python.exe client_resetdata\create_views.py`
(UTF-8 safe — needed because the Meta filter contains an en-dash; do **not** use `Get-Content | bq query`).
Then re-run the job: `gcloud run jobs execute resetdata-export --region australia-southeast1 --wait`.
