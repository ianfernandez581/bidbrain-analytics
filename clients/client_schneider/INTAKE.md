# client_schneider — intake / data slice (resolved)

**Client:** Schneider Electric (APAC) · **Agency:** Transmission · **Reporting currency:** AUD
**Status:** 🟢 Live on GCP. **Restructured 2026-06-22 into a `client_mongodb`-style 3-tab dashboard**
(Paid Media · **Content Syndication** · CS Comparison) **scoped to the 5 Salesforce lead-gen programs**
(Water & Environment, EBA, Heavy Industries, Global Rebrand, AirSeT = 9 SF campaign IDs) — the earlier
6-tab Pacific paid-media dashboard is superseded, and the other ~20 APAC programs are removed from the
dashboard (the seed tables still carry them for the match_pattern tagging). Seeds remain CSV-loaded
(`data/` → `seed_*` via `load_seeds.py`); CS targets/CPL come from the media plan. **95 in-flight
Salesforce leads** (eba 42 / water_env 28 / heavy 25 — clamped to each program's flight window, so
pre-flight spillover like EBA's 4 pre-2026-05-25 leads is excluded), all status `New`. See the
*Discrepancies* + open items below; the Pacific-carve-out history is in
[`_eda/pacific_eda.md`](_eda/pacific_eda.md).

## Pacific carve-out — open items (raised to client 2026-06-16, dashboard live with defaults applied)
The dashboard now defaults to the **Pacific** portfolio (org book of work, NOT the geographic region).
Decisions made to ship live — each is a one-line `portfolio` flip in `data/campaign_map.csv`
+ re-run `deploy_seeds_schneider.ps1`; confirm with the client. Full EDA + reconciliation in [`_eda/pacific_eda.md`](_eda/pacific_eda.md).
1. **Portfolio of the "neither-list" programs.** Pacific = the client's named 11 programs only;
   everything else (incl. `eae`, `iof`, `impact_maker`, `power_products`, `digital_*`, `modernisation`,
   `active_kpx`, `mea_seg`, `aveva`, `ia_services`) → APAC-other. Confirm.
2. **`ind_edge` + `pac_hybrid_it`** are NAMED "Pacific" in the platform but NOT on the client's program
   list → tagged **APAC-other** (the org-vs-geo trap). Flip to Pacific if they belong to the Pacific book.
3. **`ecocare` ≡ "EcoCare BMS"?** Tagged Pacific (delivery is literally `..._Ecocare_BMS_...`). Confirm.
4. **`enterprise_software`** added as a Pacific placeholder, distinct from the excluded `ent_it`
   ("Enterprise IT Expansion"). Confirm its real identity / naming when it launches.
5. **Heavy Industries** is marked LIVE by the client but has **zero warehouse delivery** under any
   naming — need the platform campaign name / PO to set a real `match_pattern` (currently `Heavy Indust*`).
6. **W&E budget conflict** (unchanged, still flagged): seed = 95,000 AUD incl-fees; W&E media plan totals
   59,111 AUD (P1 13,854 + P2 22,167 + P3 23,090). Which is canonical?
7. **NEL / New Energy Landscape** (job 2053) is delivering (2 TradeDesk campaigns) but unmapped & not on
   the Pacific list — Pacific, APAC-other, or ignore?
8. **Pacific placeholders** (Global Rebrand, Healthcare, Microgrid, Enterprise Software) seeded with
   non-matching sentinel `match_pattern`s — set the real pattern + budget/flight when each launches
   (Jul/Aug). Budgets/flight-dates/channel-splits still needed per program.
9. **FX** (USD→AUD 1.50, SGD→AUD 1.15) and **GA4** (no SE property id) unchanged — still placeholders/disabled.

## Discrepancies from the media-plan sheet (2026-06-22 — using the NEWER sheet values, flagged for sign-off)
The Pacific lead-gen budgets/targets were re-sourced from the digested media plan (`data/media_plan.csv`
+ `data/plan_budget.csv`). These **change earlier seed values** — kept the newer sheet numbers, but flag:
- **EBA MQL target 157** (sheet) vs **300** (old `seed_targets`). Using 157 (on the EBA media-plan lead line). The stale `eba,opt_in_mqls,300` row was dropped.
- **W&E budget** 81,034 ex_fees (sum of sheet lines) vs **95,000 incl_fees** (old seed). Using 81,034 ex_fees.
- **Heavy budget** 67,195 (sheet sum) vs **87,500** (old seed). Using 67,195.
- **EBA budget** 32,500 (programmatic 20,000 + lead gen 12,500) vs **20,000** (old, programmatic only). Using 32,500.
- **Global Rebrand** — no spend in the sheet → budget NULL (flight start only); the media-plan file is
  "New Energy Technology Brand", so the live campaign naming may not contain "Rebrand" — the
  `global_rebrand` `match_pattern` likely needs updating at launch.
- **NEL / New Energy Landscape** (job 2053) — not in the SF IDs sheet (no leads), but has ad delivery +
  a media plan → added as `nel`, portfolio **Pacific**. **Confirm portfolio.**
- **MQL/HQL vs raw leads** — the SF feed has no grading yet (all `New`); "leads vs MQL/HQL target" is
  raw-leads-vs-target until the CRM matures.
- **No-source targets** — Trade Publication (page views/sessions/engaged/outbound CTR), EBA IDE emails,
  Global Rebrand Search CTR + Innovation Aus views/downloads have **no warehouse source** → shown as
  target-only on the plan, never as 0 actuals.

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

**No** `stg_google` / `stg_reddit` — Schneider has **no rows** in `google_ads_apac` / `reddit_ads_apac_all`.
**`stg_salesforce` is now wired** — Schneider DOES have leads in `salesforce_cs_apac_all` (**95
in-flight leads**: `eba` 42, `water_env` 28, `heavy` 25 — clamped to each program's flight window),
joined via `seed_salesforce_map`. (Corrects the earlier "no rows in salesforce_cs_apac_all" note.)

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
6. **Leads / ABM + intent** — **Salesforce CRM leads are WIRED** and are now the whole point of the
   dashboard (the **Content Syndication** tab): lead volume is live (95 in-flight leads), but the CRM hasn't graded
   them (all status `New`), so the tab shows total CRM-raw leads vs the media-plan MQL+HQL target — not
   "MQLs achieved". The intent layer (Bombora / Demandbase / Sqreem) remains a manual feed, not wired.
7. **Search & Reddit** — planned channels (in the 2306 split) with **no warehouse delivery** —
   shown as planned budget, not zero performance.
8. **Persona / vertical / account / funnel-stage filters** — stubbed; seed-backed in a later pass.
