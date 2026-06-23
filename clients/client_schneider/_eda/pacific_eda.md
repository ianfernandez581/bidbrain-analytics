# Schneider Electric → PACIFIC carve-out — Phase-1 EDA findings

**Date:** 2026-06-16 · **Scope:** read-only EDA, **nothing changed**. · **Author:** agent (Phase 1).
**Reproduce:** `./.venv/Scripts/python.exe clients/client_schneider/_eda/run_eda.py` →
`_eda/eda_report.txt` (full tables) + `_eda/eda_summary.json` (machine). Mapping cross-checked by
`_eda/verify_mapping.py` (independent BigQuery SQL re-derivation — **0 disagreements** on all 174 campaigns).

> **STOP / checkpoint:** this is Phase 1 only. No seed/view/job/dash edit has been made. Review the
> reconciliation + open questions + the A-vs-B architecture recommendation below before I touch anything.

---

## TL;DR (read this first)
1. **The mapping engine is sound and the inventory is complete.** I ported the live dashboard's exact
   `idOf()` join (lowercase the platform campaign name → first `seed_campaign_map` row, in array order,
   whose any `|`-token is a substring → else `(unmapped)`) and verified it against a second,
   independent SQL implementation: identical on all **174** delivering campaigns. `ad_campaigns`
   captures the full SE slice (9 DV360 + 13 TradeDesk + 152 LinkedIn = 174; matches the raw mirrors).
2. **Three Pacific programs are LIVE-delivering right now and TWO of them don't map:**
   - **AirSeT** (5 LinkedIn campaigns) → **`(unmapped)`** — there is **no `airset` seed row**. Must add (job **2223**).
   - **EBA / EcoStruxure Building Activate** (`SE_EBA_Activate_AWR_June4`, TradeDesk, **2.02M imps**) → **`(unmapped)`**. Must add (job **2079**).
   - **Water & Environment** (4 campaigns) → maps fine to `water_env`, but its seed **job number 1130 is stale** (canonical **2026**).
3. **The "EBA tangled into eae" issue is at the TARGET level, not the delivery level.** EBA's *delivery*
   is unmapped (above). What's tangled is the **300 opt-in MQL target**, which sits on `eae`
   (EcoStruxure **Automation** Expert, job **1974**) but was sourced from the **EBA** (Building Activate, job 2079)
   brief. Splitting EBA into its own row + moving the target is exactly the Phase-2 fix.
4. **Most of the Pacific book hasn't launched yet** — Heavy, Global Rebrand, MCSeT-relaunch, EcoConsult,
   Healthcare, Microgrid, Enterprise Software show **no current delivery** (consistent with their
   July/Aug/TBC live dates). **Heavy Industries is the one anomaly:** the client lists it **LIVE**, but
   **zero warehouse delivery** matches it under any naming — flag (see Q4).
5. **Org-"Pacific" ≠ geo-"Pacific" — confirmed in the data.** The geographic Pacific (Fiji/PNG/island
   nations) is **negligible** (8,185 DV360 imps, 0.008%). The "Pacific"/"PAC" *market* chip is almost
   entirely **campaign-name tokens on ANZ-targeted programs** (`Pacific Hybrid IT`, `EntIT_2026_PAC`).
   The Pacific **portfolio** we're building is a name-based program grouping, unrelated to that chip.
   **The geographic region logic is left untouched** (Phase 2 will not edit any `market` parser).
6. **Currency CASE branches all validated** — DV360 carries AUD+USD+SGD (all three fire), LinkedIn
   carries all three (by `_USD/_SGD/_AUD` suffix), TradeDesk is **AUD-only** today (ELSE branch).
7. **Biggest unresolved question is portfolio assignment of the ~10 "neither-list" programs**
   (EAE, Industrial Edge, EcoCare, IA Services, Impact Maker, IOF, Power Products, Digital Buildings,
   Digital Power, Modernisation, Active KPX, Pacific Hybrid IT, MEA Segment, AVEVA). The client spec
   names 11 Pacific programs + 3 excludes, which together cover only ~14 of the 21 seed ids + the new
   adds. The rest are unassigned and several materially change the Pacific totals (see Q1).

**Recommended architecture: A** (portfolio tag + filter on the existing deployment, default Pacific,
add a Pacific / APAC-other / All toggle). Rationale at the bottom.

---

## 1. Platform campaign inventory (live SE slice, all 3 platforms)

Completeness cross-check — the `ad_campaigns` view == the raw SE slice (nothing dropped):

| Platform | Raw distinct campaigns | `ad_campaigns` view | Imps | Clicks | Date span |
|---|---|---|---|---|---|
| DV360 (`ADVERTISER_NAME LIKE 'APAC \| Schneider Electric%'`) | 9 | **9** | 98,195,707 | 270,327 | 2025-07-26 → 2026-06-09 |
| TradeDesk (`ADVERTISER_NAME = 'Schneider Electric'`) | 13 | **13** | 3,280,908 | 5,695 | 2026-04-30 → 2026-06-15 |
| LinkedIn (`ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'`) | 152 | **152** | 5,259,125 | 13,646 | 2025-06-02 → 2026-06-15 |
| **Total** | **174** | **174** | **106.7M** | **289,668** | 2025-06-02 → 2026-06-15 |

Full per-campaign inventory (every delivering campaign × imps/clicks/AUD spend/min-max date → mapped id)
is in `_eda/eda_report.txt` §1 and `_eda/eda_summary.json`. Rolled up to internal campaign:

## 2. Roster by internal id (what the dashboard's campaign filter shows today)

Sorted by AUD spend. **Portfolio col = my read of the client spec** (✅ = explicitly in a spec list;
❓ = *not* covered by either list → open question; ⚠️ = needs confirmation).

| id | display | #camps | spend AUD | imps | platforms | window | portfolio (proposed) |
|---|---|--:|--:|--:|---|---|---|
| `csp` | C&SP Relationship Marketing | 26 | 92,418 | 10.0M | dv360,li | 2025-09 → 2026-03 | **APAC-other** ✅ (excluded) |
| `ai_lc` | AI & Liquid Cooling | 14 | 56,248 | 12.9M | dv360,li,td | 2025-11 → 2026-06 | **APAC-other** ✅ (excluded) |
| `impact_maker` | Impact Maker | 1 | 33,336 | 19.2M | dv360 | 2025-11 → 2026-03 | ❓ unassigned |
| `eae` | EcoStruxure **Automation** Expert | 1 | 28,329 | 13.8M | dv360 | 2025-12 → 2026-06 | ❓ unassigned (job→**1974**) |
| `iof` | Industries of the Future | 5 | 25,332 | 33.0M | dv360,li | 2025-10 → 2026-02 | ❓ unassigned |
| `ent_it` | Enterprise IT Expansion | 35 | 21,810 | 1.0M | li,td | 2026-05 → 2026-06 | **APAC-other** ✅ (excluded) |
| `power_products` | Power Products (ANZ) | 1 | 21,000 | 10.3M | dv360 | 2025-11 → 2026-04 | ❓ unassigned |
| `ecocare` | EcoCare | 22 | 20,599 | 0.42M | li | 2025-08 → 2025-12 | **Pacific?** ⚠️ (= "EcoCare BMS"? Q2) |
| `digital_power` | Digital Power Basket | 18 | 15,295 | 0.46M | li | 2025-12 → 2026-03 | ❓ unassigned |
| `modernisation` | Modernisation / SPaaS | 8 | 11,839 | 0.22M | li | 2025-08 → 2025-12 | ❓ unassigned |
| `pac_hybrid_it` | Pacific Hybrid IT | 7 | 11,830 | 0.17M | li | 2025-06 → 2025-09 | **Pacific?** ⚠️ (geo-Pacific name; Q1) |
| `mea_seg` | MEA Segment Program | 5 | 11,713 | 0.76M | dv360,li | 2025-06 → 2025-09 | ❓ unassigned (MEA, likely other) |
| `digital_bldg` | Digital Buildings | 4 | 11,578 | 1.25M | dv360,li | 2025-08 → 2025-11 | ❓ unassigned |
| `ind_edge` | Industrial Edge / Prefab | 4 | 8,662 | 0.08M | li | 2025-10 → 2025-12 | **Pacific?** ⚠️ (region=Pacific; job→**2463**; Q1) |
| `ia_services` | IA Services | 3 | 8,235 | 0.05M | li | 2026-03 → 2026-06 | ❓ unassigned (job→**2280**) |
| `mcset` | MCSeT + EvoPacT | 2 | 7,558 | 0.46M | dv360,li | 2025-08 → 2025-09 | **Pacific** ✅ (job→**2389**; Q3) |
| **`(unmapped)`** | — | **10** | **6,151** | 2.16M | li,td | 2025-09 → 2026-06 | see §2b |
| `active_kpx` | Active KPX | 4 | 3,329 | 0.15M | li | 2025-10 → 2025-12 | ❓ unassigned |
| `water_env` | Water & Environment | 4 | 3,167 | 0.25M | li,td | 2026-04 → 2026-06 | **Pacific** ✅ (job→**2026**) |

Seeded-but-not-delivering ids: **`heavy`** (Pacific ✅, job 2281 — Q4), **`ecoconsult`** (Pacific ✅, job 2279),
**`aveva`** (❓ unassigned — still no delivery, as INTAKE already flagged).

### 2b. The `(unmapped)` bucket (10 campaigns, 2.16M imps, A$6,151)

| Platform | Imps | AUD | Campaign | Belongs to |
|---|--:|--:|---|---|
| tradedesk | 2,022,891 | 2,623 | `SE_EBA_Activate_AWR_June4` | **EBA** (Pacific, job 2079) — add row |
| linkedin | 127,750 | 2,886 | `1839_..._Pacific_All_Industrial_TAL_&_Job_Edge_Awareness` | Industrial Edge (1839) — pattern misses it (Q5) |
| linkedin | 4,775 | 217 | `1839_..._Pacific_All_Industrial_TAL_&_Job_Edge_Consideration` | Industrial Edge (1839) — pattern misses it (Q5) |
| linkedin | 1,326 | 30 | `RM AirSeT – Awareness – AU` | **AirSeT** (Pacific, job 2223) — add row |
| linkedin | 1,241 | 29 | `SM AirSeT – Awareness – AU` | **AirSeT** |
| linkedin | 1,217 | 73 | `RM AirSeT – Retargeting – ANZ` | **AirSeT** |
| linkedin | 776 | 55 | `SM AirSeT – Retargeting – ANZ` | **AirSeT** |
| linkedin | 506 | 15 | `RM AirSeT – Awareness – NZ` | **AirSeT** |
| tradedesk | 2,872 | 198 | `SE_NEL_TTD_AWR_AU_Jun26` | **NEL / New Energy Landscape** (job 2053) — Pacific or other? (Q6) |
| tradedesk | 390 | 25 | `SE_NEL_TTD_AWR_NZ_Jun26` | **NEL** |

> **AirSeT naming gotcha:** the AirSeT campaigns use a literal **en-dash `–` (U+2013)** as separator,
> not a hyphen. The substring token `airset` is unaffected (it's a clean substring), so a
> `match_pattern` of `AirSeT` will catch all 5. Validated against the unmapped list.

## 3. Pacific program delivery status (the 11 from the spec)

| # | Pacific program | Spec status | Job# (canonical) | Seed id today | Delivering now? | Evidence |
|--:|---|---|---|---|---|---|
| 1 | Heavy Industries | LIVE | 2281 | `heavy` (job —) | **NO** ⚠️ | no campaign matches `Heavy Indust*` on any platform (Q4) |
| 2 | AirSeT | LIVE | 2223 | **missing** | **YES** (5, A$202) | `RM/SM AirSeT – … – ANZ/AU/NZ` → currently `(unmapped)` |
| 3 | EBA (Building Activate) | LIVE | 2079 | **missing** (target on `eae`) | **YES** (1, A$2,623, 2.0M imps) | `SE_EBA_Activate_AWR_June4` → `(unmapped)` |
| 4 | Water & Environment | LIVE | 2026 | `water_env` (job **1130** stale) | **YES** (4, A$3,167) | `SE_WaterEnv_P2_AWR/Cons – AU/NZ`, from 2026-04-29 |
| 5 | Global Rebrand Activation | live July (channels TBD) | — | missing | NO (expected) | no `rebrand`/`global rebrand` campaign |
| 6 | MCSeT & EvoPacT | live July | 2389 | `mcset` (job **1130** stale) | **historical only** | 2 `1130_Cooling Solutions…` camps ran Aug–Sep **2025**; July 2026 relaunch not yet live (Q3) |
| 7 | EcoConsult | live July | 2279 | `ecoconsult` (job —) | NO (expected) | no `ecoconsult` campaign; budget/targets/flighting already seeded |
| 8 | Healthcare | live July/Aug | — | missing | NO (expected) | "Healthcare" appears only as an **audience segment** of other campaigns (ent_it/ecocare/mea_seg/digital_bldg), not its own program |
| 9 | Microgrid | live Aug | — | missing | NO (expected) | no `microgrid` campaign |
| 10 | EcoCare BMS | live TBC | — | `ecocare`? ⚠️ | **YES** (22, A$20,599) — *if* ≡ `ecocare` | delivery literally `1967_SE_Ecocare_BMS_*` + `PO1787_…EcoCare_*` (Q2) |
| 11 | Enterprise Software | live TBC | — | missing ⚠️ | NO | no `enterprise software` campaign; **do not** conflate with `ent_it` (Q7) |

## 4. Geography reality check (org-Pacific vs geo-Pacific)

**ANZ-dominant, confirmed.** DV360 (the only platform with a real geo column): **Australia 59.9M +
New Zealand 16.9M = 76.8M of 98.2M imps ≈ 78%**. Raw `COUNTRY_NAME` top rows: AU, NZ, IN, MY, TH, SG,
PH, VN, JP, ID, then AE/ZA/US tail.

**The geographic "Pacific" region (island nations) is negligible:**
- DV360 `market='Pacific'` (FJ/PG/NC/VU/SB/WS/TO/PF/… per `stg_dv360`): **8,185 imps (0.008%)**.
- LinkedIn `market='Pacific'`: 236k imps — but this is the **campaign-name parser** firing on the
  `Pacific`/`PAC` token, and those campaigns are ANZ-targeted programs (`Pacific Hybrid IT`,
  `EntIT_2026_PAC_*`). TradeDesk `market='Pacific'`: 106k imps = `SE_EntIT_2026_PAC` (Enterprise IT,
  which is **excluded** from the Pacific portfolio).

**→ The distinction holds and matters.** "Pacific" as the existing **Geography-tab region chip** is a
near-empty geographic slice plus a few ANZ campaign-name tokens. "Pacific" as the **portfolio** we're
building is an *organisational* set of SE programs (Heavy, AirSeT, EBA, W&E, …) defined by program
membership, **independent of geography**. Note the trap: `SE_EntIT_2026_PAC` parses to *market* Pacific
yet its *program* (`ent_it`) is excluded — geography and portfolio are orthogonal. **Phase 2 will add a
new `portfolio` dimension and will NOT touch any `market`/region parser.**

## 5. Currency check (validates the FX CASE branches in stg_*)

| Platform | Currencies present (by rows / imps) | FX branch exercised |
|---|---|---|
| DV360 | **SGD** 44.4M imps · **AUD** 43.4M · **USD** 10.4M | all three (`USD×1.50`, `SGD×1.15`, else AUD) ✅ |
| LinkedIn (acct suffix) | **AUD** 2.37M · **USD** 2.11M · **SGD** 0.79M | all three (`_USD×1.50`, `_SGD×1.15`, else AUD) ✅ |
| TradeDesk | **AUD only** (25,608 rows) | ELSE branch only; USD/SGD dormant but robust ✅ (matches `stg_tradedesk` header) |

FX rates `USD→AUD 1.50` / `SGD→AUD 1.15` are **hardcoded placeholders** in every `stg_*` spend CASE —
unchanged here; flagged for confirmation (Q9), do not touch without sign-off.

## 6. Reconciliation table + open questions

**Pacific program ↔ canonical job# ↔ seed id ↔ delivering? ↔ unmapped delivery that belongs to it.**
(Note: the spec's job numbers are **brief** job numbers; campaign names carry **platform PO** codes,
which differ — e.g. `csp` brief 1957 ↔ PO 1608. So a mismatch between job# and the number in a campaign
name is expected and *not* an error. The `match_pattern` substring, not the job number, is the bridge.)

| Pacific program | Canonical job# | Seed id | Seed job# now | Delivering? | Action for Phase 2 |
|---|---|---|---|---|---|
| Heavy Industries | 2281 | `heavy` | — | **no** | set job 2281; investigate why LIVE but no delivery (Q4) |
| AirSeT | 2223 | **none** | — | **yes (5)** | **ADD** row, pattern `AirSeT`, job 2223, Pacific |
| EBA / Building Activate | 2079 | **none** (≠ `eae`) | — | **yes (1)** | **ADD** row, pattern `EBA` (validate), job 2079; move 300-MQL target off `eae` |
| Water & Environment | 2026 | `water_env` | **1130** ✗ | yes (4) | fix job 1130→2026 |
| MCSeT & EvoPacT | 2389 | `mcset` | **1130** ✗ | historical | fix job 1130→2389 |
| EcoConsult | 2279 | `ecoconsult` | — | no | set job 2279 (already budget/target/flight-seeded) |
| Global Rebrand | — | none | — | no | ADD placeholder (Pacific, no delivery) |
| Healthcare | — | none | — | no | ADD placeholder |
| Microgrid | — | none | — | no | ADD placeholder |
| EcoCare BMS | — | `ecocare`? ⚠️ | — | yes (22) if ≡ | confirm `ecocare`≡EcoCare BMS before tagging (Q2) |
| Enterprise Software | — | none ⚠️ | — | no | ADD placeholder; **NEEDS-CONFIRMATION**, ≠ `ent_it` (Q7) |
| *(reference)* EAE Automation Expert | 1974 | `eae` | — | yes (1) | set job 1974; **portfolio = ? (Q1)** — not in either spec list |
| *(reference)* Industrial Edge W3 | 2463 | `ind_edge` | **1839** | yes (4) | fix job 1839→2463; **portfolio = ? (Q1)** — region=Pacific but not in spec list |

### Open questions (need your call before / during Phase 2)

- **Q1 — Portfolio of the "neither-list" programs (the big one).** The spec lists 11 Pacific + 3 excludes;
  that leaves **~10 delivering seed ids unassigned**: `eae`, `ind_edge`, `ecocare`, `ia_services`,
  `impact_maker`, `iof`, `power_products`, `digital_bldg`, `digital_power`, `modernisation`,
  `active_kpx`, `pac_hybrid_it`, `mea_seg`, `aveva`. Some look Pacific (`ind_edge` region=Pacific;
  `pac_hybrid_it` name; `ecocare`=EcoCare BMS?), most look like the legacy ANZ/APAC book. **Default
  proposal:** tag the 11 spec programs + AirSeT/EBA as `Pacific`; tag everything else (incl. the 3
  excludes) `APAC-other`; flag `ind_edge`/`ecocare`/`pac_hybrid_it` for your confirmation. Confirm or
  correct. (This materially changes the Pacific totals — see below.)
- **Q2 — EcoCare BMS ≡ existing `ecocare`?** Delivery is literally `1967_SE_Ecocare_BMS_*`, so almost
  certainly yes — but you flagged not to guess. Confirm so I can tag `ecocare` Pacific (vs leaving it other).
- **Q3 — MCSeT.** Spec says "live July" but the only delivery is a 2025 `Cooling Solutions` flight.
  Treat `mcset` as a Pacific program with historical delivery + a July-2026 relaunch? (job → 2389 regardless.)
- **Q4 — Heavy Industries: LIVE but zero delivery.** No campaign matches `Heavy Indust*` on any platform.
  Possible causes: not yet trafficked, a different platform name, or the TTD connector gap (CLAUDE.md notes
  the Windsor TTD connector is down — but TradeDesk here comes via `raw_snowflake`, which *is* flowing).
  Do you have the platform campaign name / PO so I can set a real `match_pattern`?
- **Q5 — Two `1839_…_Pacific_All_Industrial_TAL_&_Job_Edge_*` campaigns are unmapped.** They're PO 1839
  (Industrial Edge) but say "Job_Edge"/"All_Industrial", not "Industrial Edge", so the pattern misses them.
  Extend `ind_edge` pattern to catch them, or leave unmapped?
- **Q6 — NEL / New Energy Landscape (job 2053)** is delivering (2 TradeDesk campaigns, A$223) but is **not
  in your Pacific 11**. It's AU/NZ-targeted. Pacific portfolio, APAC-other, or ignore?
- **Q7 — Enterprise Software identity.** No delivery; must **not** be conflated with `ent_it` (Enterprise IT,
  excluded). Add as an empty Pacific placeholder pending its real identity? Same question for **EcoCare BMS**
  if you decide it's *not* `ecocare`.
- **Q8 — W&E budget conflict** (raised in the brief, restating): seed says **95,000 AUD incl-fees**; the W&E
  media plan totals **59,111 AUD** (P1 13,854 + P2 22,167 + P3 23,090, Mar–Sep 2026). Which is canonical?
- **Q9 — FX placeholders** (`USD→AUD 1.50`, `SGD→AUD 1.15`) unconfirmed and hardcoded in every `stg_*`. Leave as-is?
- **Q10 — GA4** stays shipped-disabled (no SE property id). Confirm Pacific view keeps the "awaiting GA4
  property id" stub (no change).

> **What "default to Pacific" looks like in current delivery.** If Pacific = {the spec's 11 + AirSeT + EBA}
> *strictly* (i.e. `ind_edge`/`ecocare`/`pac_hybrid_it` → APAC-other), the default Pacific view is **small
> and early**: only **W&E (A$3.2k), EBA (A$2.6k), AirSeT (A$0.2k)** are live now, plus MCSeT's historical
> A$7.6k; the rest launch Jul–Aug. If `ecocare`(A$20.6k)+`ind_edge`(A$8.7k)+`pac_hybrid_it`(A$11.8k) are
> *in*, Pacific roughly **7×** in spend. **Q1/Q2 decide whether the Pacific dashboard looks empty or full**
> — worth resolving up front.

---

## Architecture recommendation: **A** (portfolio filter on the existing deployment)

**Recommend A** — add a `portfolio` tag to `seed_campaign_map`, default the campaign roster /
`activeInternal` to `portfolio='Pacific'`, and add a small **Portfolio toggle (Pacific / APAC-other /
All)** defaulting to Pacific. One pipeline, one dataset/bucket/service/URL/password.

Why A over B (separate `client_schneider_pacific` deployment):
- **Lowest effort, fully reversible** — it's a `portfolio` column carried through the 3-file contract
  (`data/campaign_map.csv`, loaded by `load_seeds.py` → `job/main.py` seed dict → `dashboard.html` META + default filter) plus a
  toggle. No new dataset, bucket, Cloud Run service, SA, IAM, secret, scheduler, or domain.
- **The data is one slice.** All three platforms are filtered to the *same* SE advertiser; Pacific is a
  re-grouping of the same 174 campaigns, not a different data source. B would clone the entire pipeline to
  serve a filtered subset of identical data — pure duplication and a second freshness gate to maintain.
- **Pacific is largely pre-launch (Jul–Aug).** Programs will flip live over the next two months; a tag +
  toggle absorbs that with seed edits only. A separate deployment would need parallel redeploys each time.
- **Excluded books stay one toggle away**, which is what Gabby's team will want for cross-checks, rather
  than logging into a second dashboard.

**Choose B only if** the client explicitly wants a **distinct URL / password / domain** for the Pacific
team (access separation), or wants the APAC-other programs *invisible*, not just filtered out. If so I'll
clone the archetype to `client_schneider_pacific` and scope it to Pacific with no toggle.

**Defaulting to A unless you say B.**

---

### Artifacts in `_eda/`
- `run_eda.py` — the EDA (read-only); regenerates the two outputs below.
- `eda_report.txt` — full human-readable tables (inventory, roster, unmapped, program probe, geo, currency, seed order).
- `eda_summary.json` — machine-readable summary (inventory, roster, unmapped, program_probe, currency, market).
- `verify_mapping.py` — independent SQL re-derivation of the join; **PASSED** (0 disagreements / 174 campaigns).
