# client_schneider — intake / data slice (resolved)

**Client:** Schneider Electric (APAC) · **Agency:** Transmission · **Reporting currency:** AUD
**Status:** 🟢 Live on GCP (stood up 2026-06-04). 11 of the 21 mapped campaigns have seeded plan
budgets; the rest are still TODO (see open items below).

> The data slice was **resolved before the build** (filters below are applied verbatim in the
> `stg_*` views). The DV360 `COUNTRY_NAME` enumeration was run once to ground the market mapping;
> the LinkedIn/TradeDesk/DV360 campaign names were read from the BigQuery mirror to ground the
> region parser and the `seed_campaign_map.match_pattern` bridge. No other Snowflake exploration.

## Resolved filters (in the staging views)
| Platform | Raw table | Filter | Currency → AUD |
|---|---|---|---|
| **DV360** | `raw_snowflake.dv360_apac` | `ADVERTISER_NAME LIKE 'APAC \| Schneider Electric%'` | `REVENUE_ADV_CURRENCY`, USD×1.50 / SGD×1.15 / else as-is |
| **TradeDesk** | `raw_snowflake.tradedesk_apac_all` | `ADVERTISER_NAME = 'Schneider Electric'` | `COSTS`, USD×1.50 / SGD×1.15 (all AUD today) |
| **LinkedIn** | `raw_snowflake.linkedin_ads_apac` | `ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'` (3 accts: `_USD` 2.1M imps, `_AUD` 2.0M, `_SGD` 0.79M) | `COSTS`, inferred from acct suffix |

**No** `stg_google` / `stg_reddit` / `stg_salesforce` — Schneider has **no rows** in those raw tables.

## FX (placeholders — confirm with client)
`FX_USD_AUD = 1.50`, `FX_SGD_AUD = 1.15`. Set once in each `stg_*` spend CASE + surfaced in `kpi`.

## Market mapping (per the brief, grounded in data)
- DV360 `COUNTRY_NAME` (global delivery, dominated by **AU 60M + NZ 17M imps = ANZ**) → fine market
  (AU/NZ/India/Singapore/… kept) then grouped to brief regions (ANZ / India / SEA / MEA / South
  America / Japan / Pacific; global spill → East Asia / South Asia / Europe / North America / RoW).
- LinkedIn / TradeDesk have no geo column → region parsed from `CAMPAIGN_NAME` (observed tokens:
  AU, NZ, ANZ, India, SEA + countries, MEA + UAE/KSA, SAM/Brazil/Chile, Japan, Pacific/PAC).
- The AU/NZ ~80/20 split is preserved (fine market) and surfaced on the Geography tab.

## Open items handed to the client / for a later pass (seed TODOs)
1. **GA4 (Website tab)** — SE GA4 **property id(s) unknown** → views ship with a placeholder, the
   tab shows the "awaiting GA4 property id" stub, and `GA4_ENABLED=False`. Provide ids to switch on.
2. **FX rates** — confirm 1.50 / 1.15.
3. **`aveva`** — in the plan but **no delivery** matched any platform campaign (no `AVEVA` in the
   warehouse) → flagged TODO in `seed_campaign_map`. Confirm it launched / its platform naming.
4. **`brief_job_no` ↔ platform PO** — intentionally **not reconciled** (a human task). The
   `match_pattern` CONTAINS is the only bridge (e.g. csp brief 1957 ↔ platform PO 1608).
5. **Budgets / targets / flighting / flight dates** — only the brief-stated numbers are seeded
   (W&E 95k incl-fees; ai_lc/2306 480.6k ex-fees; Heavy 87.5k ex-fees; EBA→eae 300 opt-ins;
   EcoConsult 100% traffic / 25 SQL / 20 consults / ≥40% webinar + 35/45/10/10 flighting). The rest
   are NULL/TODO — complete from the media plans. `EBA≡eae` and `Heavy`/`EcoConsult` campaign
   identities need confirming.
6. **Leads / ABM + intent** — CaptureIQ + Bombora / Demandbase / Sqreem are a **manual feed not yet
   wired**; platform leads (LinkedIn forms) + conversions (DV360/TradeDesk) are shown as a proxy.
7. **Search & Reddit** — planned channels (in the 2306 split) with **no warehouse delivery** —
   shown as planned budget, not zero performance.
8. **Persona / vertical / account / funnel-stage filters** — stubbed; seed-backed in a later pass.
