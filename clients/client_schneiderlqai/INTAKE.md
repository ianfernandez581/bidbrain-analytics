# INTAKE — Schneider Liquid AI Data Center (LQAIDC)

Source material in `raw_files/`:
- `2306 - SE AI and Liquid Cooling - Dashboard Brief.pdf` — the media plan / brief (targets below).
- `SCHNEIDER LQAI LINKEDIN CAMPAIGN IDS.xlsx` — LinkedIn campaign 951901366 + 6 country ad sets.
- `SCHNEIDER LQAI TRADEDESK CAMPAIGN IDS.xlsx` — Trade Desk campaign `ekse5e8` + 6 country ad groups
  (its "Tab 1_data" sheet also dumps the whole Schneider TTD account incl. the separate
  `1958_SE_EntIT_*` Enterprise IT brief — OUT OF SCOPE for this dashboard).

## What the data is (EDA, 2026-07-20)
- **LinkedIn** `raw_snowflake.linkedin_ads_apac`, account `SchneiderElectric_TransmissionSG_AUD`,
  campaign group `2306_SE_LQAIDC_LI_TOFU_May26` (id 951901366), 6 country ad sets. Data from 2026-05-16.
  Objective "Website visits" -> **Leads = 0** (awareness). ~1.24M imps / 5.2k clicks / A$19.8k to date.
- **Trade Desk** `raw_snowflake.tradedesk_apac_all`, advertiser `Schneider Electric`, campaign
  `2306_SE_LQAIDC_TTD_TOFU_May26` (id `ekse5e8`), 6 country ad groups, display banners. Data from
  2026-05-18. **Convs = 0**. ~0.8M imps / 1.8k clicks / A$13.4k to date. Partner "Transmission Media AU".
- **Name-form quirk:** the raw campaign name gained a `2306_` prefix on ~6-7 Jul 2026 (LinkedIn group +
  TTD campaign), same ids. The `'%LQAIDC%'` scope filter rolls up both forms.

## Media-plan targets (from the brief; whole flight 15 May - 31 Dec 2026)
Loaded via `data/media_plan.csv` -> `seed_media_plan`. `live=1` = currently delivering.

| Channel | Phase | Imp target | Reach | Click target | CTR | Spend | Live |
|---|---|--:|--:|--:|--:|--:|:--:|
| Programmatic - Trade Desk (Premium Publishers) | Awareness | 5,696,000 | 1,898,667 | 17,088 | 0.30% | A$85,440 | yes |
| Programmatic - Trade Desk (TAL / Intent) | Awareness | 3,500,000 | 1,898,667 | 17,088 | 0.30% | A$53,400 | yes |
| LinkedIn | Awareness | 925,600 | 231,400 | 5,091 | 0.55% | A$69,420 | yes |
| Search | Awareness | 7,476,000 | - | - | 3.00% | A$67,284 | no (tbc) |
| Reddit | Awareness | 1,483,333 | 296,667 | 4,450 | 0.30% | A$26,700 | no (tbc) |
| Programmatic - Trade Desk (Retargeting) | Retargeting | 6,408,000 | 1,281,600 | 19,224 | 0.30% | A$96,120 | no |
| LinkedIn (Retargeting) | Retargeting | 830,667 | 276,889 | 6,645 | 0.80% | A$74,760 | no |

- **Live budget** (the 3 live Awareness lines) = **A$208,260**; **full plan** = **A$473,124**.
- Per-channel live targets the dashboard paces against: **LinkedIn** 925,600 imp / 5,091 clk / A$69,420;
  **Trade Desk** 9,196,000 imp / 34,176 clk / A$138,840 (the two TTD Awareness lines summed — the single
  live TTD campaign doesn't distinguish Premium-Publishers vs TAL/Intent).

## Assumptions / decisions (flag for the client)
1. **Currency of targets = AUD.** The brief spend figures are shown with a bare `$`; the raw delivery is
   AUD (account `_AUD`, TTD currency AUD) and this is a Transmission-AU / Schneider-Pacific buy, so the
   targets are treated as AUD. If the plan `$` is actually USD, gross the target budgets by the FX rate.
2. **Scope = LQAIDC only.** Confirmed by the brief (channels = Trade Desk / LinkedIn / Search / Reddit)
   and the client's own LinkedIn file + TTD "Sheet1" pivot, which isolate LQAIDC. Enterprise IT
   (`1958_SE_EntIT`) is a separate brief and excluded.
3. **Reach is plan-only.** The raw ad platforms don't expose delivered reach here, so impressions are the
   delivered reach proxy; delivered CTR is measured.
4. **TTD Awareness split.** Both TTD Awareness lines are folded into one live target because the single
   live TTD campaign carries no Premium-Publishers vs TAL/Intent split. Edit `data/media_plan.csv`
   `live` flags if that changes (e.g. when Retargeting / Search / Reddit launch).
