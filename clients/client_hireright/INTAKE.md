# client_hireright — build intake (resolved slice)

A generic paid-media **delivery** baseline — "all of HireRight's paid media in one place." Cloned from
`client_STT`, with the GA4 / website half stripped out and a third platform (The Trade Desk) added. No
media plan, no targets, no seeds, no GA4. This file records the resolved slice the build was made from.

## Platforms & filters (the only client-specific bits)

| Platform | Raw table | Filter (BigQuery-valid) | Currency | Market |
|---|---|---|---|---|
| DV360 | `raw_snowflake.dv360_apac` | `LOWER(ADVERTISER_NAME) LIKE '%hireright%'` | already USD | `COUNTRY_NAME` (real geo — the only source with it) |
| The Trade Desk | `raw_snowflake.tradedesk_apac_all` | `ADVERTISER_NAME = 'HireRight'` | AUD → USD | `'Global'` (campaign names are persona/TAL) |
| LinkedIn | `raw_snowflake.linkedin_ads_apac` | `LOWER(ACCOUNT_NAME) LIKE 'hireright%'` | USD (`_AUD` acct → USD) | `'Global'` (audience NAM/EMEA/APAC combined) |

> The brief specified the filters with Snowflake `ILIKE` / `LIKE … ESCAPE`. These views run as **BigQuery**
> views, which have neither, so they are expressed as `LOWER(col) LIKE '…'` and `ENDS_WITH(col, '_AUD')` —
> same intent, valid Standard SQL.

**No** `stg_google` / `stg_reddit` / `stg_salesforce` / `stg_ga4` views were built: HireRight has no rows in
Google Ads, Reddit or Salesforce, and its GA4 property can't be identified.

## Currency

Reporting currency = **USD**. One FX constant: `FX_AUD_USD = 0.65` (placeholder — editable). Applied where
each AUD source is staged (`sql/03_stg_tradedesk.sql`, and the `_AUD` guard in `sql/02_stg_linkedin.sql`)
and surfaced as `fx_aud_usd` in `sql/05_kpi.sql`. Only TradeDesk is actually AUD today; DV360 and LinkedIn
are already USD.

## Confirmed against the raw layer at build time

Window **2025-10-25 → 2026-06-02**:

| Platform | Rows | Window | Spend |
|---|---|---|---|
| DV360 | 18,490 | 2025-11-16 → 2026-01-30 | ~$14.9k USD · 15 country markets |
| LinkedIn | 2,106 | 2025-10-25 → 2026-04-17 | ~$22.6k USD |
| TradeDesk | 2,188 | 2026-03-29 → 2026-06-02 | A$6.8k → ~$4.4k USD |

Combined ≈ **$42k USD**. (Numbers are point-in-time; the live dashboard always reflects the current data.)

## Deliverable

A 2-tab dashboard (Overview · Paid Media) that renders fully from delivery alone — see the
[client README](README.md). Filters: Platform · Campaign · Market. Reporting in USD.
