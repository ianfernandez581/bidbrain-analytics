# client_STT/sql/ — the BigQuery views (stage-2 transform)

One `CREATE OR REPLACE VIEW` per file, applied in filename order by
[`../create_views.py`](../create_views.py) (the `NN_` prefix enforces dependency order: the `stg_*`
filter views first, then the roll-ups that read them). The export job
([`../job/main.py`](../job/main.py)) `SELECT`s the roll-ups to assemble `stt.json`.

| File | View | What it does |
|---|---|---|
| `01_stg_ga4.sql` | `stg_ga4` | **GA4 filter** — the 11 `STT GDC Web *` properties. Derives `market` + a coarse `channel_bucket` (Paid/Organic/Direct/Referral/Other). |
| `02_stg_linkedin.sql` | `stg_linkedin` | **LinkedIn filter** — `ACCOUNT_NAME = 'STTGDC_TransmissionSG_USD'` (USD). |
| `03_stg_dv360.sql` | `stg_dv360` | **DV360 filter** — the single Always On campaign (SGD). Maps `COUNTRY_NAME` → market. |
| `04_kpi.sql` | `kpi` | One-row headline metrics for the campaign window + prior-year baseline. Holds `FX_USD_SGD = 1.34`. |
| `05_monthly.sql` | `monthly` | Per-month GA4 (by bucket) + LinkedIn + DV360 — the hero trend (from 2025-01). |
| `06_ga4_channels.sql` | `ga4_channels` | Sessions by default channel group (campaign window). |
| `07_ga4_markets.sql` | `ga4_markets` | Sessions by market / property, with paid/display/social split. |
| `08_ga4_sources.sql` | `ga4_sources` | Top 40 source/medium — where the ad platforms surface by name. |
| `09_li_creative.sql` | `li_creative` | LinkedIn by creative type. |
| `10_li_campaigns.sql` | `li_campaigns` | LinkedIn by campaign. |
| `11_dv_markets.sql` | `dv_markets` | DV360 by market (SGD spend). |
| `12_weekly.sql` | `weekly` | Per-ISO-week ad delivery vs Display+Social sessions — the Ads→Traffic correlation. |

**The filter + the FX/window constants are the only STT-specific bits.** The account list lives once in
`stg_ga4`; the LinkedIn account and DV360 campaign live once in `stg_linkedin`/`stg_dv360`; everything
downstream reads those three. To change the reporting FX or campaign-window start, edit the literals in
`04_kpi.sql`, `05_monthly.sql`, `12_weekly.sql`.

Apply:  `python client_STT/create_views.py`
