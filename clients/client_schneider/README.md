# clients/client_schneider/ — Schneider Electric **Pacific** · **live (deployed 2026-06-04)**

> **Dashboard branded "Pacific"** (a sibling Schneider Electric dashboard for another SE region is
> planned, so this one is explicitly the Pacific book). The underlying programme is still Schneider's
> APAC Content Syndication, scoped to the Pacific markets / 5 lead-gen programs.
>
> Schneider Electric's APAC **Content Syndication** programme (run via the agency **Transmission**) —
> a [`client_mongodb`](../client_mongodb/README.md)-style dashboard scoped to the **5 Salesforce
> lead-gen programs**. Filter the shared raw layers to SE's slice, model it in BigQuery views, export
> one JSON, serve it from a password-gated web app. Reporting currency **AUD**.

**Plain English:** Schneider runs lead-gen ("content syndication") for 5 programs — **Water &
Environment, EBA, Heavy Industries, Global Rebrand, AirSeT** — backed by 9 Salesforce campaigns. This
dashboard (modelled on MongoDB's) shows, per program: live **Salesforce leads vs the media-plan MQL+HQL
target** (Content Syndication tab), the **DV360 / Trade Desk / LinkedIn paid delivery** behind them
(Paid Media tab), and a **market-vs-market comparison** (CS Comparison tab).

**Status:** 🟢 **Live on GCP.** Restructured **2026-06-22** into a **3-tab mongodb clone** (Paid Media ·
Content Syndication · CS Comparison) **scoped to the 5 lead-gen programs** — the earlier 6-tab Pacific
paid-media dashboard is superseded. 28 BigQuery views + 7 CSV-loaded `seed_*` tables; `schneider.json`,
the `schneider-export` job and `schneider-dash` service deployed; the `*/10` self-gating scheduler runs.
Salesforce leads are **CRM-raw** (all status `New` — the CRM hasn't graded MQL/SQL/HQL yet), so the CS
tab shows total leads vs target, not "MQLs achieved". Targets/CPL come from the media plan
(`data/media_plan.csv`, version-controlled — the committed-CSV→BQ targets standard); see
[`INTAKE.md`](INTAKE.md) for the client-flagged discrepancies (EBA MQL 157
vs old 300, W&E/Heavy/EBA budgets, NEL added).

**Update 2026-07-02** (dash rev `schneider-dash-00021`): (0) the campaign dropdown now leads with an
**"All campaigns" portfolio view** (a synthesized pseudo-campaign summing all 5 across the Paid Media,
Content Syndication and CS Comparison tabs — helpers use an `inCamp()` match-all predicate; the "Other
Channels" tab stays per-campaign), and the dashboard **defaults to it** (`activeCampaign = ALL_ID` on
boot; flip back to a single default by restoring `cs[0].id`). (1) the **Campaign selector moved to a
dropdown in the top nav bar** (Cloudflare pattern), off the control-bar filter row. (2) **Region simplified to
Australia + New Zealand** — the ANZ and Other chips are gone. (3) **EBA (EcoStruxure Building Activate)
paid media now renders**: its Trade Desk delivery (5.2M imps / A$6.3k) was always in BigQuery but the
region was parsed only from the campaign name, so it fell into the "Other" bucket (`SE_EBA_Activate_AWR_June4`
has no country in the campaign name — the AU/NZ split lives in the ad-group names). `sql/03_stg_tradedesk.sql`
now reads the country from `AD_GROUP_NAME` first, splitting EBA into Australia (A$5.0k) + New Zealand (A$1.3k);
AirSeT's Trade Desk resolves the same way. The **Heavy Industries trade-publication** thought-leadership line
was already in the plan and renders under **Heavy → Other Channels** (a plan-only line — a publisher
sponsorship has no ad-platform feed, so only its plan targets show).

**Update 2026-07-03** (`dash/dashboard.html` + `dash/report.py`; needs a `schneider-dash` redeploy to go live):
(1) the deck **cover/eyebrow brand** now reads **"TRANSMISSION × Schneider Electric Pacific"** (was "…Schneider
Electric" — `BB_THEME.brand`); every other surface already said "Schneider Electric Pacific". (2) **Spend vs budget**
(client ask, from Gabby): the **Paid Media** tab has a new **"Spend vs budget"** card — measured DV360/TTD/LinkedIn
spend vs the planned media-plan **paid-media budget**, plus a time-to-date (elapsed-flight pro-rata) pace. It is
**whole-flight / all-markets** (independent of the region + date filters, which the plan budget isn't split by), so
label it as such. The **Content Syndication** tab's leads-vs-target note now also shows **≈ est. spend (delivered
leads × plan CPL) of the committed CS budget**. All budget maths is **client-side** from the already-emitted
`campaigns[].channels[]` (`spend` + `group`) + `committed_spend` — **no job / view / seed change** (verified: All-
campaigns paid budget A$163,441, CS committed A$97,288, total A$270,729 = Σ `plan_budget.budget_aud`). The deck
payload gains a `plan.budget` block (`paid` / `paid_spend` / `paid_ttd` / `cs_committed` / `cs_est_spend` / `total`),
and `report.py`'s per-client guardrail now tells the model to surface an explicit spent-vs-budgeted **budget** KPI
(paid = measured, CS = estimated / per-lead, kept distinct).

**Update 2026-07-08** (`sql/20_pm_delivery.sql` + `job/main.py` + `dash/dashboard.html`; deployed):
added **NEL (New Energy Landscape, brief 2053)** as a **6th program**. Unlike the 5 CS programs, NEL is
**awareness-only** (no Salesforce lead-gen) — it has real LinkedIn + Trade Desk paid delivery (the
`SE_NEL_2026_ANZ_LI_Awareness` LinkedIn group + `*_NEL_TTD_*` Programmatic, AU + NZ, ~A$5.0k so far) but
**no CS leads**, so it renders **Paid Media only** (like `global_rebrand`). NEL was already in the seed
CSVs (`campaign_map`/`media_plan`/`plan_budget`, `internal_campaign_id='nel'`, match_pattern `NEL|New
Energy Landscape`), so the change was just: add `'nel'` to the `WHERE program IN (…)` in
[`sql/20_pm_delivery.sql`](sql/20_pm_delivery.sql) and to `CS_PROGRAMS` in [`job/main.py`](job/main.py),
plus a `PILLAR` entry for it in the dashboard. It sorts last in the Campaign dropdown (0 leads / 0
target) so the default campaign is unchanged, and it appears as a 0/0 awareness card in the Executive
Scorecard (same as `global_rebrand`). No seed reload was needed.

**Update 2026-07-31** (`sql/20_pm_delivery.sql` + `job/main.py` + `dash/dashboard.html` + `data/*.csv`):
added **Microgrid (brief 2040)** as a **7th program** — the same awareness-only shape as NEL (real paid
delivery, no Salesforce CS leads, so it renders **Paid Media only**). LinkedIn is the only channel
delivering: two ad sets in `SchneiderElectric_TransmissionSG_AUD`,
`2040 SE_Microgrid-Broad_July2026-ANZ-Static` and `…-Video`, **live since 2026-07-27** (first 4 days:
21,546 imps / 31 clicks / **A$423.98**, CTR 0.14%, CPM A$19.68). **No Trade Desk and no DV360 delivery**
exists for this brief. `microgrid` was already row `seq=25` in `data/campaign_map.csv` and its existing
`Microgrid` token tags both ad sets first-match-wins with **no collision**, so enabling it was the NEL
two-liner: add `'microgrid'` to the `WHERE program IN (…)` in
[`sql/20_pm_delivery.sql`](sql/20_pm_delivery.sql) and to `CS_PROGRAMS` in [`job/main.py`](job/main.py),
plus a `PILLAR` entry ("Energy Resilience") in the dashboard. Also set its `brief_job_no` to **2040** and
added **`2040 SE` + `2040_`** match_pattern tokens — defensive, per the `heavy`/`2281_` lesson that the
delivering ad-set names can abbreviate away the program word (no such sibling exists today; verified).
**Targets: impressions seeded, rest PENDING** — the client confirmed a **70,680 impression target**
(2026-08-06, seeded on `data/media_plan.csv`'s LinkedIn Awareness line via `load_seeds.py` + a forced
job run), so the scorecard card now paces reach against it. Spend/flight dates are still blank
(`data/plan_budget.csv` still has a blank `microgrid` row) until a signed media plan lands
(fill the CSVs and re-run `load_seeds.py` + the job with `FORCE_REBUILD=1`). **Market caveat:** both ad
sets are named `-ANZ-` with no country token, and LinkedIn has no ad-group column to fall back on the way
Trade Desk does, so `sql/20`'s AU/NZ normalisation folds **100% of Microgrid delivery into Australia**.
An AU/NZ split is not derivable from this feed - it needs country-specific campaign names.

**Update 2026-08-05** (`sql/20_pm_delivery.sql` + `job/main.py` + `dash/dashboard.html` + `data/*.csv`):
added **EcoConsult (brief 2279)** as an **8th program** — paid-only like NEL/Microgrid (real paid
delivery, no Salesforce CS leads, renders **Paid Media only**). LinkedIn is the only channel (no TTD,
no DV360): 6 ad sets in `SchneiderElectric_TransmissionSG_AUD` under 3 campaign groups
(`2279_SE_EcoConsult_ECAA_2026_ANZ_{Awareness,Consideration,Conversion}`), **live since 2026-07-21**
(through 08-04: 72,587 imps / 128 clicks / **A$2,859.49**). The delivering ad-set names are
`2279_SE_EcoConsult_2026_ANZ_Persona{A-CSuite,B-Eng,BC-EngOps,C-Ops}_{Carousel,DocAd,SingleImg}` —
`ecoconsult` was already row `seq=22` in `data/campaign_map.csv` and its `EcoConsult` token tags all 6
first-match-wins with no collision (verified), so enabling it was the NEL two-liner: add `'ecoconsult'`
to the `WHERE program IN (…)` in [`sql/20_pm_delivery.sql`](sql/20_pm_delivery.sql) and to
`CS_PROGRAMS` in [`job/main.py`](job/main.py), plus a `PILLAR` entry ("Services & Consulting") in the
dashboard. **`ECAA` + `2279_`** match_pattern tokens added — defensive, per the `heavy`/`2281_` lesson.
**Targets: impressions seeded, rest PENDING** — the client confirmed a **333,333 impression target**
(2026-08-06, seeded on `data/media_plan.csv`'s LinkedIn Awareness line via `load_seeds.py` + a forced
job run), so the scorecard card now paces reach against it. The rest of the plan is still blank
(`data/plan_budget.csv` already had ecoconsult at A$30,000 ex-fees from the Pacific intake, no flight
dates) until the signed plan lands (fill the CSVs, re-run `load_seeds.py` + the job `FORCE_REBUILD=1`).
**Market caveat (same as Microgrid):** every ad-set name is `_ANZ_` with no country token and LinkedIn
has no ad-group fallback, so `sql/20` folds **100% of EcoConsult delivery into Australia**.
**Lead-gen caveat:** 2 of the 3 groups are LinkedIn Lead Generation objective. Those lead-form leads
are **NOT** Salesforce CS leads — the CS lane stays Salesforce-only (the `heavy` precedent), so when SE
provision a Salesforce campaign for EcoConsult, add its SF id to `salesforce_map` to light up the CS
tabs. They now surface as a separate **paid** metric on the Paid Media tab — see *Update 2026-08-06*.

<<<<<<< HEAD
=======
<<<<<<< Updated upstream
=======
>>>>>>> 18be5ac (park: WIP from charles)
## SCOPE RULE — the dashboard shows the client's intake sheet, NOT everything that delivers
**Client, 2026-08-10:** *"there are 3 campaigns on the dashboard that shouldn't be. These are separate
campaigns with separate stakeholders. Please only put the campaigns that we have input to the sheet."*
On 2026-08-10 three programs were added and **REMOVED the same day** on that instruction:
**Enterprise IT Expansion (`ent_it`, 1958)**, **Industrial Edge / Prefab (`ind_edge`, 2463)** and
**Software First EcoStruxure (`software_first`, 2305)**.

**Delivering under the Schneider advertiser/account does NOT mean in scope.** Before adding any
program here, confirm it is on the client's intake sheet. The scope lives in exactly two places that
must stay in sync — `CS_PROGRAMS` in [`job/main.py`](job/main.py) and the `WHERE program IN (…)` in
[`sql/20_pm_delivery.sql`](sql/20_pm_delivery.sql).

### What the removal did and did not touch
Reverted: both scope lists; the `WHEN cm.program IN ('ent_it')` multi-region market arm in `sql/20`;
`ind_edge`'s `match_pattern` (back to the bare `Industrial Edge`); the `software_first` row in
`campaign_map.csv`; the two `ent_it` rows in `media_plan.csv`; `ent_it`'s `plan_budget` flight_end.
The seed CSVs are byte-identical to their pre-2026-08-10 state, and all 8 remaining programs verified
unchanged after the revert.
**KEPT** (independent of those campaigns, both still correct and in use):
- **`pm_delivery` is AGGREGATED** — see below.
- **Per-campaign Region chips** (`campaigns[].markets` + `marketRoster()`/`syncMarketRoster()`),
  `channels[].flight_start/_end`, `campaigns[].objective` + `objWord()`. One visible effect: a program
  with delivery in only one country now shows only that chip (EcoConsult and Microgrid show
  **Australia** only, where the old global roster showed a dead New Zealand chip too).

### If any of the three is ever re-added — what it took (so it isn't re-derived)
- **`ent_it` needs the multi-region market arm restored FIRST.** Its ad groups are region-coded
  (`SE_EntIT_2026_{PAC,India,MEA,SAM}_*`) with **no country token**, and only ~12% of its delivery is
  Pacific — `sql/20`'s AU/NZ fold is an `ELSE`, so adding it to the scope list alone silently reports
  **A$44,346 of MEA / India / South America spend AS AUSTRALIA**. The arm and the reasoning are
  recorded in the `sql/20` market comment. Scale at removal: LinkedIn 21 ad sets + TTD 12 campaigns,
  2,880,437 imps / **A$60,039**, live since 2026-05-06. Note it also raised the **portfolio Executive
  Scorecard** totals, which are whole-portfolio and region-filtered.
- **`ind_edge` needs its match_pattern narrowed.** The bare `Industrial Edge` token also sweeps in the
  **2025 `1839_Schneider_Electric_Pacific_*` wave** (Sep-Dec 2025, A$8,662) — a different brief. The
  client scoped it to **Wave 3 / 2463 only**, which needs
  `SE_Industrial Edge_|Industrial Edge Wave3|Industrial Edge W3|2463_` (simulated clean: exactly the
  10 Wave-3 lines, zero 2025 rows, zero collisions). Scale: 213,660 imps / **A$4,323**, AU+NZ, live
  since 2026-07-06, plus 1 LinkedIn lead-form lead / 71 form opens.
  *LinkedIn campaign-GROUP names are unreliable here — a group named
  `2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named `2463_SE_Industrial Edge Wave3_*`,
  while the `2463_…` group holds the un-prefixed `SE_Industrial Edge_*` campaigns. Key off CAMPAIGN
  names, never the group's brief number.*
- **`software_first` has NO `campaign_map` row** — its delivery is unmatched and invisible to every
  view. Re-adding needs a row appended **at the highest `seq`** (last place means first-match-wins can
  only give it campaigns nothing else claims, so it cannot steal delivery from an existing program),
  tokens `Software First|EcoStruxureIT|2305_`. **`2305_` alone is NOT enough:** the TTD line ran as
  `SE_EcoStruxureIT_AWR_2026` from 2026-06-17 and gained the prefix on 07-06, so a prefix-only token
  drops A$2,296 (the repo-wide "campaign names are NOT stable keys" rule). Scale: 448,433 imps /
  **A$9,821**. Its display name says "Software First EcoStruxure" while the TTD line says
  "EcoStruxureIT" — same brief. `seq=26` `enterprise_software` remains an inert placeholder
  (`Enterprise_Software_TBC`); merge only if SE confirm 2305 IS that programme.

### Known unmatched delivery (deliberate — audit output, not a bug to fix blindly)
Since 2026-07-01, delivery under the Schneider advertiser/account that maps to **no** program:
<<<<<<< HEAD
the 5 `software_first` lines (A$8,144+). Programs that are mapped but simply out of scope (e.g.
`ai_lc`, which has its own **schneiderlqai** dashboard) are not "gaps".

**`mcset` was on this list until 2026-08-11 — now RESOLVED and IN SCOPE** (client request). Its
`match_pattern` really was mis-seeded as `Cooling Solutions`, which matched none of its
`SE_MCSet_*` names and instead claimed two **brief-1130** campaigns from Aug-Sep 2025 (a finished,
unrelated Cooling Solutions event: A$7,558 across LinkedIn + DV360). Dropping that token was the
"scope decision" this note called for — folding a year-old brief into a 2026 launch would have
inflated it roughly 9x and stretched its date axis across a year. The pattern is now
`MCSet|EvoPact|2389_`; the swap was simulated against `stg_ad_delivery` first and moved exactly
5 campaigns (3 gained, the 2 stale 1130 ones released), stealing nothing from any other program.
=======
the 5 `software_first` lines (A$8,144+), and **`mcset` (brief 2389), which is MIS-SEEDED** — its
`match_pattern` is `Cooling Solutions`, matching none of its real `SE_MCSet_*` campaign names
(A$542 and growing since 2026-08-05). MCSeT is **deliberately deferred** (client, 2026-08-10: revisit
after the platform launch) and needs BOTH a token fix and a scope decision. Programs that are mapped
but simply out of scope (e.g. `ai_lc`, which has its own **schneiderlqai** dashboard) are not "gaps".
>>>>>>> 18be5ac (park: WIP from charles)

### `pm_delivery` is AGGREGATED (2026-08-10, kept)
`GROUP BY program, platform, metric_date, market`. The view carries **no campaign column**, so the
ungrouped version emitted one duplicate row per delivering campaign/ad group and every consumer summed
them anyway — which had pushed `schneider.json` to **13.6 MB** (73,509 rows). Grouping cut it to
**~0.3 MB / ~1,400 rows** with byte-identical totals, verified program-by-program against the
ungrouped output (every delta exactly zero). `SUM(leads)` over an all-NULL DV360/TTD group still
returns NULL, so the "NULL not 0 off LinkedIn" contract survives the rollup. **Keep this GROUP BY** —
if a campaign-grain view is ever needed, add a SEPARATE view rather than un-grouping this one.

<<<<<<< HEAD
=======
>>>>>>> Stashed changes
>>>>>>> 18be5ac (park: WIP from charles)
**Update 2026-08-06** (`sql/04_stg_ad_delivery.sql` + `sql/20_pm_delivery.sql` + `job/main.py` +
`dash/dashboard.html`): four fixes, all triggered by the Executive Scorecard drawing **`0 / 0 leads` +
`no flight dates`** on EcoConsult and Microgrid while both were demonstrably delivering.

1. **LinkedIn lead-form leads now reach the dashboard.** `stg_linkedin` had always carried LinkedIn's
   own `LEADS` / `LEAD_FORM_OPENS`, but **`sql/04_stg_ad_delivery.sql` dropped them** (it selected only
   imps/clicks/spend), so `pm_delivery` never saw them and EcoConsult's leads existed nowhere on the
   dash. Both columns are now carried 04 → 20 → `job/main.py` → the UI, **`NULL` (not 0) for
   DV360/TradeDesk** — those staging views have no conversion feed, and 0 would read as "measured none".
   Verified against LinkedIn's own reporting: **EcoConsult 3 leads / 13 form opens** (all on the
   Consideration `PersonaBC-EngOps_DocAd` ad set), and this also surfaced **5 previously-invisible NEL
   lead-form leads** (4 AU + 1 NZ). Surfaced as: a **Lead-form leads** KPI card + a **Lead-form leads**
   column on the platform table (both auto-hidden when the filtered selection has none, so an awareness
   program never shows an implied 0-lead failure), an awareness-card footer line, `paid.totals
   .lead_form_leads` / `by_platform[].lead_form_leads` in the AI-deck payload, and the CSV exports.
   **They are a PAID metric and must never be summed into a CS lead total** — the whole point of the
   `heavy` precedent. Every layer carries that warning in a comment.
2. **Flight dates fall back to OBSERVED delivery.** `flight_start`/`flight_end` come from
   `data/plan_budget.csv` → `seed_plan_budget` → `job/main.py`; EcoConsult has a budget but **blank
   dates**, Microgrid is **blank entirely**, because neither media plan is signed. `job/main.py` now
   falls back to the program's **first delivery day** when the plan seeds no start at all, and emits
   **`flight_source`** (`'plan'` | `'observed'`) + `first_delivery` / `last_delivery`. The **end is
   never synthesized** (an unsigned plan has no agreed end, and a missing end already means "ongoing"),
   and a plan start with an open end — `global_rebrand` — is left exactly as seeded. The UI labels an
   observed window **"live since 21 Jul"**, never "flight". Deck payload carries `flight_source` with a
   note not to describe an observed window as a planned flight.
3. **Awareness programs are paced on REACH, not leads.** The scorecard card had one shape (leads vs
   target) and `paceVerdict` returned the literal string `'no flight dates'` for *any* null pace —
   including a null caused by a **0 lead target**, which is why NEL showed "no flight dates" despite
   having them. Cards now branch: a program with no MQL+HQL target renders **impressions vs the media
   plan's paid `imp_target`** (`progImpTarget`, summed over `channels[]` where `group==='paid'`), with
   delivered CPM, spend to date, lead-form leads and the flight anchor, and its own `reachVerdict`
   (*Ahead of / Behind reach plan* · **awareness - targets pending** when no plan is signed · *awareness
   - no delivery yet*). NEL therefore gets a real pace (**340,695 of 814,861 planned impressions**);
   EcoConsult/Microgrid read "targets pending" with their true reach instead of a 0%-filled lead bar.
   The portfolio strip gained an **Impressions delivered** KPI and its "Programs live" caption now
   splits *lead-gen · awareness* (it used to call all 8 "lead-gen programs").
4. **`Platform` filter (new, resetdata pattern, Schneider-styled).** Programs run several engines at
   once, so a **DV360 / TradeDesk / LinkedIn** chip group sits ahead of the Region chips (same `.chip`
   pill, platform brand dot instead of the tick; `All` / `Clear` actions; a chip **dims** when that
   engine has no delivery for the selected program but stays togglable). State = `activePlatforms`,
   predicate = `platOk()`, wired into **`pmRows()`** (so the whole Paid Media tab — KPIs, hero chart,
   platform + market tables, doughnuts, CSV) and **`progPaid()`** (so the scorecard's reach KPIs and
   awareness cards follow it too). It is deliberately **hidden on Content Syndication / CS Comparison /
   Other / Website**: Salesforce leads have no delivering platform, so filtering them by engine would
   silently zero a real number. `buildDeckPayload()` **restores all platforms** before building (like
   it already nulls the date range) so a chip left off on screen can't drop an engine from a client deck.

Also fixed in passing: **`tableCSV()` leaked `_`-prefixed internal stashes** — `bbApplySpendMult` parks
each row's pre-markup spend on `_rawSpend`, and `pm_delivery` exports were shipping it to the client.
Underscore keys are now dropped from the header and every row (the repo-wide rule in `md/AGENTS.md`).

## Data model (mongodb concept → Schneider source)
- **Campaign** (**top-nav dropdown** in the nav bar — the Cloudflare `dash-select` pattern) = the 5
  CS programs (`water_env` · `eba` · `heavy` · `global_rebrand` · `airset`) **+ `nel`** (New Energy
  Landscape; added 2026-07-08) **+ `microgrid`** (brief 2040; added 2026-07-31) **+ `ecoconsult`**
  (brief 2279; added 2026-08-05) — the last three are paid-only, Paid-Media-tab-only, no CS leads.
<<<<<<< HEAD
  **Scope = the client's intake sheet** — three other delivering programs were added and removed again
  on 2026-08-10 at the client's request; see the SCOPE RULE section above before adding a 9th.
=======
<<<<<<< Updated upstream
>>>>>>> 18be5ac (park: WIP from charles)
- **Programme** (the CS breakdown) = the Salesforce `pillar_label` (9), from `seed_salesforce_map`.
- **Market / Region chips** are **PER CAMPAIGN** (`campaigns[].markets`), not one global list:
  - Pacific programs = **Australia / New Zealand only** (no ANZ, no Other). CS leads are AU/NZ-native;
    paid delivery's AU/NZ split is resolved from **`AD_GROUP_NAME`** (then `CAMPAIGN_NAME`) in
    `sql/03_stg_tradedesk.sql` — several ANZ-level campaigns (EBA `SE_EBA_Activate_AWR_June4`, AirSeT
    `SE AirSeT_ANZ_HighImpact…`) carry the country only in the ad-group name, so the old
    campaign-name-only parse stranded that delivery (notably **all of EBA's Trade Desk** — 5.2M imps)
    in an Unmapped/Other bucket. `sql/20_pm_delivery.sql` folds any tiny unsplittable combined-ANZ
    residual (e.g. AirSeT's `RM AirSeT – Retargeting – ANZ` LinkedIn line, ~$500) into **Australia**.
  - Every program in scope today is AU/NZ, so a program with delivery in only one country shows only
    that chip (EcoConsult, Microgrid = **Australia** only).
  - **A non-AU/NZ program needs a multi-region arm added to `sql/20` FIRST** — the AU/NZ fold is an
    `ELSE`, so without it 100% of that program's foreign delivery reports as Australia, silently. The
    arm and the worked example (`ent_it`) are in the `sql/20` market comment.
  - The GLOBAL tabs (Executive Scorecard, Website) use the portfolio union `all_markets`.
- **Target** (per campaign) = Σ MQL+HQL `lead_target` from `seed_media_plan`; **Plan CPL tiers** = each
  lead line's spend ÷ lead_target; **committed spend** = Σ lead-line spend; **flight** from
  `seed_plan_budget` (program-level) — **per-CHANNEL flights** live on `channels[].flight_start/_end`
  from `seed_media_plan`, for a program whose channels end on different dates.
- **Scoped to the 8:** `pm_delivery` (`sql/20`) is `WHERE program IN (the 5 CS programs + 'nel' +
  'microgrid' + 'ecoconsult')`; the CS views read only the 9 SF ids via `seed_salesforce_map` (NEL,
  Microgrid and EcoConsult have none, so they never appear in the CS tabs). The old Pacific
  `portfolio` toggle and the other ~20 APAC programs
  are **gone from the dashboard** — the seed tables still carry them for the `match_pattern` tagging.
<<<<<<< HEAD
=======
=======
  **Scope = the client's intake sheet** — three other delivering programs were added and removed again
  on 2026-08-10 at the client's request; see the SCOPE RULE section above before adding a 9th.
- **Programme** (the CS breakdown) = the Salesforce `pillar_label` (9), from `seed_salesforce_map`.
- **Market / Region chips** are **PER CAMPAIGN** (`campaigns[].markets`), not one global list:
  - Pacific programs = **Australia / New Zealand only** (no ANZ, no Other). CS leads are AU/NZ-native;
    paid delivery's AU/NZ split is resolved from **`AD_GROUP_NAME`** (then `CAMPAIGN_NAME`) in
    `sql/03_stg_tradedesk.sql` — several ANZ-level campaigns (EBA `SE_EBA_Activate_AWR_June4`, AirSeT
    `SE AirSeT_ANZ_HighImpact…`) carry the country only in the ad-group name, so the old
    campaign-name-only parse stranded that delivery (notably **all of EBA's Trade Desk** — 5.2M imps)
    in an Unmapped/Other bucket. `sql/20_pm_delivery.sql` folds any tiny unsplittable combined-ANZ
    residual (e.g. AirSeT's `RM AirSeT – Retargeting – ANZ` LinkedIn line, ~$500) into **Australia**.
  - Every program in scope today is AU/NZ, so a program with delivery in only one country shows only
    that chip (EcoConsult, Microgrid = **Australia** only).
  - **A non-AU/NZ program needs a multi-region arm added to `sql/20` FIRST** — the AU/NZ fold is an
    `ELSE`, so without it 100% of that program's foreign delivery reports as Australia, silently. The
    arm and the worked example (`ent_it`) are in the `sql/20` market comment.
  - The GLOBAL tabs (Executive Scorecard, Website) use the portfolio union `all_markets`.
- **Target** (per campaign) = Σ MQL+HQL `lead_target` from `seed_media_plan`; **Plan CPL tiers** = each
  lead line's spend ÷ lead_target; **committed spend** = Σ lead-line spend; **flight** from
  `seed_plan_budget` (program-level) — **per-CHANNEL flights** live on `channels[].flight_start/_end`
  from `seed_media_plan`, for a program whose channels end on different dates.
- **Scoped to the 8:** `pm_delivery` (`sql/20`) is `WHERE program IN (the 5 CS programs + 'nel' +
  'microgrid' + 'ecoconsult')`; the CS views read only the 9 SF ids via `seed_salesforce_map` (NEL,
  Microgrid and EcoConsult have none, so they never appear in the CS tabs). The old Pacific
  `portfolio` toggle and the other ~20 APAC programs
  are **gone from the dashboard** — the seed tables still carry them for the `match_pattern` tagging.
>>>>>>> 18be5ac (park: WIP from charles)
- **A program's SCOPE is its `match_pattern`, not just the IN-list.** A programme name can span several
  waves/briefs (`ind_edge`'s bare `Industrial Edge` token also catches a 2025 wave) — before adding any
  program, simulate its pattern against `SELECT DISTINCT campaign FROM stg_ad_delivery` and check both
  what it catches and what else claims those campaigns.
<<<<<<< HEAD
=======
>>>>>>> Stashed changes
>>>>>>> 18be5ac (park: WIP from charles)
  (Historical Pacific-carve-out EDA: [`_eda/pacific_eda.md`](_eda/pacific_eda.md).)

---

## What's different from STT (the archetype)
- **It's a [`client_mongodb`](../client_mongodb/) clone, not the STT layout** — 3 tabs, a single-select
  Campaign control, Region chips + a date picker, scoped to the 5 lead-gen programs (Schneider skin —
  the mongodb *layout*, Schneider's green/dark theme + logo).
- **Three ad platforms** (DV360 + TradeDesk + LinkedIn), AUD (USD→AUD @1.50, SGD→AUD @1.15 placeholders;
  LinkedIn currency inferred from the `_USD`/`_AUD`/`_SGD` account suffix). **No GA4 website tab** in the
  clone (the `40–46 ga4_*` views still apply but are unused by the job).
- **Salesforce Content Syndication is the focus**: `stg_salesforce` + `cs_by_programme` / `cs_weekly`
  (`sql/17–19`) read SE's 9 SF campaigns via `seed_salesforce_map`; `pm_delivery` (`sql/20`) tags paid
  delivery to its program via the `match_pattern` join (replicating the old client-side `idOf` in SQL,
  first-match-wins by `seq`), scoped to the 5.
- **Seeds are CSV-loaded** via [`load_seeds.py`](load_seeds.py) into `seed_*` tables. The media-plan
  **targets** (`media_plan` / `targets` / `plan_budget`) **and `campaign_map`** (campaign display names +
  match_patterns) live in [`data/`](data/), version-controlled via `.gitignore` `!` exceptions; the
  remaining dimension seeds also read from `data/` (gitignored / BQ-only — see *Updating targets*).

## The dashboard tabs (`dash/dashboard.html`) — a global **Executive Scorecard** + **per-campaign** tabs
**Executive Scorecard** (default tab, added 2026-07-06) is **global / portfolio-wide** — it spans all 5
programs (region-filterable; the Campaign dropdown is hidden here) and reframes the dashboard from lead
*volume* to lead *quality*, per the deep-research finding that senior B2B marketers value quality/pacing
over raw counts. It shows: portfolio KPIs (leads vs target, pace vs plan, **accounts reached**, blended
plan CPL); **program × Schneider-strategy-pillar** pace cards (each program tagged with the corporate
pillar it advances — Advancing Energy Technology / EcoStruxure Buildings / AirSeT SF6-free / Water &
Environment / Heavy Industries); a **job-function** doughnut + **seniority** bar; and a **top-accounts**
(ABM) list. All from `21_cs_audience` (account / function / seniority from the Salesforce feed's
`COMPANY_NAME`/`JOB_FUNCTION`/`JOB_LEVEL` — verified 100%/100%/~40% populated; industry/asset/state/revenue
are empty for SE so are intentionally not shown). `renderScorecard()` in `dashboard.html`.

The remaining tabs are **per-campaign**. Filters: **Campaign** (the 8 programs) is a **dropdown in the top nav bar** (Cloudflare pattern); the
**Platform** chips (DV360 / TradeDesk / LinkedIn — added 2026-08-06), **Region** chips (Australia /
New Zealand) + **Date range** stay on the control bar under the tabs. **Platform scopes paid delivery
only** — it drives `pmRows()` (the whole Paid Media tab) and `progPaid()` (the scorecard's reach KPIs +
awareness cards), and is **hidden on Content Syndication / CS Comparison / Other / Website**, where the
numbers are Salesforce leads with no delivering platform. A chip **dims** when that engine has no
delivery for the selected program. `Date range` likewise only scopes Paid Media.
**The tab bar adapts to the selected campaign** — each campaign shows only the channels it actually
uses. The job derives `campaigns[].tabs` from that campaign's media-plan channels
([`data/media_plan.csv`](data/media_plan.csv) `channel` column, bucketed by `chan_group`):
**Paid Media** (a Programmatic/LinkedIn line, or real `pm_delivery`), **Content Syndication** (a
lead-gen line, or real leads), and **CS Comparison** (only when the campaign has leads). (An **Other
Channels** tab for plan-only lines — Search, publisher sponsorships, trade press, email — was
removed from the UI 2026-07-06 at the client's request, then **restored 2026-07-20** when the client
wanted the Heavy Industries trade-publication article-delivery table back; `campaignTabs()` no longer
filters `other` out, so the `tab-other` pane + `renderOther`/`ARTICLE_DELIVERY` code is live again.) Live result: `eba`/`water_env` → Paid·CS·Compare; `airset` → Paid·CS; `heavy` →
Paid·CS·Compare; `global_rebrand` → Paid only. Default campaign = the one with most leads (EBA today);
default tab = its first per-campaign tab; the global **Executive Scorecard** is shown **last**.
The tab bar is built in `renderControls()`; switching campaign resets to a valid tab (`setCampaign`).

1. **Paid Media** — for the selected program: KPI snapshot (spend / imps / clicks / blended CPC), a
   **platform comparison** table (DV360 / TTD / LinkedIn), a daily delivery chart (Month/Week/Day +
   Relative/Absolute toggles), spend-by-platform + spend-by-market, a market table, and the **Flight
   windows across the portfolio** Gantt. **Global Rebrand (Advancing Energy Technology)** now has LinkedIn
   delivery (its `SE_AET_*` campaigns, live from July 2026 — see *Updating targets* on the `match_pattern`
   token that tags them to `global_rebrand`). **Heavy** now has a LinkedIn Lead Generation campaign booked:
   **`2281_HeavyIndustries_Linkedin_ANZ`** (LinkedIn campaign id 1186555246, account 517045062 =
   `SchneiderElectric_TransmissionSG_AUD` — already inside the `stg_linkedin` account filter). Its name has
   NO separator between "Heavy" and "Industries", so heavy's `campaign_map` `match_pattern` gained
   `HeavyIndustries|2281_` tokens (2026-07-24; `2281_` also catches any sibling line under the same brief,
   the same way LQAIDC names carry a `2306_` prefix). **The `2281_` token is the one doing the work:**
   `2281_HeavyIndustries_LinkedIn_ANZ` turned out to be the campaign-GROUP name — the delivering ad sets
   (Snowflake `CAMPAIGN_NAME`) abbreviate to **`2281_HI_*`** (`2281_HI_P3_OAI_LeadGen_ANZ`,
   `2281_HI_P2_EnergyTransformation_LeadGen_ANZ`), which no Heavy/HeavyIndustries token matches. LinkedIn
   delivery is live since 2026-07-23 (day 1: 710 imps / 4 clicks / ~A$54, `_ANZ` → folded to Australia),
   alongside the **Trade Desk Programmatic** line `2281_SE Heavy Industries_AWR AU` (delivering since
   2026-07-15; that name HAS the space, so the old `Heavy Indust` token caught it). Lead-gen-form leads
   (`LEADS`/`LEAD_FORM_OPENS` in the raw) reach the dashboard through the Salesforce CS lane, not
   `pm_delivery`.
2. **Content Syndication** — Salesforce leads vs the media-plan **MQL+HQL** target: the snapshot strip
   (Overall / Pacing / Delivery / Outlook), the **Plan-CPL** banner, **Leads-vs-target** + **Progress**
   panels, a **Weekly pacing** chart (real dated weekly leads vs the even target pace — both start at the
   campaign's **first actual-lead week**, not its booked flight_start, since paid media often runs weeks
   before the first CS lead lands), **Leads-by-market**
   + **Leads-by-programme** doughnuts, a by-market summary, and a programme × market table. Leads are
   **CRM-raw** (`New`) — total leads vs target, not "MQLs achieved".
3. **CS Comparison** — pick two markets (e.g. Australia vs New Zealand) for the selected program and
   compare lead volume, share, programme mix and weekly pacing side by side.

## How it works (3 stages — same shape as every client)
```
 (1) SOURCE → RAW (shared)              (2) RAW → VIEWS → JSON              (3) JSON → FRONTEND
 snowflake_data_pull fills              clients/client_schneider/sql/*.sql filter   schneider-dash (Cloud Run service)
 raw_snowflake.{dv360_apac,             SE's slice + roll it up + seeds;    shows a login page, then
 tradedesk_apac_all, linkedin_ads_apac} schneider-export (Cloud Run JOB)    dashboard.html, which fetches
 (google_analytics_apac_all when GA4 on) reads views → schneider.json       /data.json and draws the charts
```
Read-only on BigQuery (it only SELECTs views + writes JSON). No `src_*` landing, no bootstrap failure.

| What to change | Edit | Stage |
|---|---|---|
| SE filter / FX rate | `sql/01_stg_dv360.sql` · `02_stg_linkedin.sql` · `03_stg_tradedesk.sql` (+ `05_kpi.sql`) | 2 |
| Media-plan **targets** (media_plan / targets / plan_budget) + **campaign_map** (display names / match_patterns) | `data/*.csv` (version-controlled — tracked via `.gitignore` `!` exceptions) → re-run `load_seeds.py` | 2 |
| Other seeds (plan_flighting / channel_split / salesforce_map) | `data/*.csv` → `load_seeds.py` (NB: currently BQ-only, no committed CSV) | 2 |
| CS + paid views (`stg_salesforce` / `cs_by_programme` / `cs_weekly` / `pm_delivery`) | `sql/17–20_*.sql` | 2 |
| A new **paid delivery metric** (must pass the unified base first) | `sql/04_stg_ad_delivery.sql` → `sql/20_pm_delivery.sql` → `job/main.py` (`pm_delivery` rows) → `dash/dashboard.html` (`pmTotals`) — 04 silently dropping a column is how LinkedIn's lead-form leads went missing (see Update 2026-08-06) | 2+3 |
| Flight window for a program | `data/plan_budget.csv` (`flight_start`/`flight_end`) → `load_seeds.py`; blank start ⇒ `job/main.py` falls back to first delivery and flags `flight_source='observed'` | 2 |
<<<<<<< HEAD
=======
<<<<<<< Updated upstream
| Which programs are in scope (the 5 CS programs + `nel` + `microgrid` + `ecoconsult`) | `data/salesforce_map.csv` (the 9 SF ids, CS only) + the `CS_PROGRAMS` list in `job/main.py` + `WHERE program IN (…)` in `sql/20_pm_delivery.sql` | 2 |
=======
>>>>>>> 18be5ac (park: WIP from charles)
| Which programs are in scope (the 5 CS programs + `nel` + `microgrid` + `ecoconsult`) — **confirm it is on the client's intake sheet first** | `data/salesforce_map.csv` (the 9 SF ids, CS only) + the `CS_PROGRAMS` list in `job/main.py` + `WHERE program IN (…)` in `sql/20_pm_delivery.sql` | 2 |
| Add a program that has NO map row yet (its delivery is currently unmatched/invisible) | append a row to `data/campaign_map.csv` **at the highest `seq`** — last place means first-match-wins can only give it campaigns nothing else claims — then the 2 scope edits above | 3 |
| Which CAMPAIGNS a program claims (e.g. scoping to one wave of a repeating brief) | `match_pattern` in `data/campaign_map.csv` → `load_seeds.py` → the first-match-wins join in `sql/20`. Simulate before committing — see `ind_edge` Wave 3 | 1 |
| Add a program that runs OUTSIDE Australia/New Zealand | the two above **PLUS** a multi-region arm ahead of the AU/NZ fold in `sql/20_pm_delivery.sql` (`WHEN cm.program IN ('<id>') THEN d.market`; the comment there has the worked example) — miss this and 100% of its foreign delivery reports as Australia, silently | 3 |
<<<<<<< HEAD
=======
>>>>>>> Stashed changes
>>>>>>> 18be5ac (park: WIP from charles)
| JSON shape | `job/main.py` (the `env = {...}` dict) | 2 |
| Charts / tabs / branding | `dash/dashboard.html` | 3 |
| Login / how JSON is served | `dash/main.py` (rarely) | 3 |

### Updating targets (committed CSV → BQ)

The media-plan **targets** are the version-controlled source of truth in [`data/`](data/)
(`media_plan.csv`, `targets.csv`, `plan_budget.csv`, `campaign_map.csv`). `data/` is gitignored
repo-wide (`clients/*/data/*`), so those four files are **kept tracked by explicit `!` exceptions in
the root `.gitignore`** — edit them freely and they travel with the repo (other clients keep their
tracked targets in a separate `targets/` dir; schneider consolidated everything into `data/`). To
change a target: edit the CSV → `.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py`
(all seeds now load from `data/`) → run the export job with `FORCE_REBUILD=1`. The remaining seeds
(plan_flighting / channel_split / salesforce_map) stay **gitignored / BQ-only** (no committed CSV);
add matching `.gitignore` `!` exceptions if you want schneider fully repo-reproducible.

## Deploy / refresh (copy-paste, PowerShell)
Project `bidbrain-analytics`, region `australia-southeast1`. **First-time stand-up:** run
[`deploy_schneider.ps1`](deploy_schneider.ps1) once (idempotent — bucket, dataset, SAs, IAM, secrets,
both Cloud Run units, scheduler; its step [5/7] now loads the seed CSVs before applying the views).
Note `deploy_schneider.ps1` seeds the scheduler at a fixed daily cron; [`scheduler.ps1`](scheduler.ps1)
flips it to the binding `*/10` self-gating cadence (the live schedule). **Prefer the per-stage scripts**
— [`deploy_seeds_schneider.ps1`](deploy_seeds_schneider.ps1) (edited `data/*.csv`),
[`sql/deploy_views_schneider.ps1`](sql/deploy_views_schneider.ps1) (edited a view — loads seeds first),
[`job/deploy_job_schneider.ps1`](job/deploy_job_schneider.ps1) (edited `job/main.py`),
[`dash/deploy_dash_schneider.ps1`](dash/deploy_dash_schneider.ps1) (edited the dashboard). The raw
commands each wraps:

```powershell
# ⓪ edited a seed CSV (data/*.csv) — reload the seed_* tables, then re-run the job (FORCE_REBUILD,
#    because seeds are NOT an upstream the freshness gate watches). load_seeds.py runs BEFORE views.
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# ① refresh data now (scheduler schneider-export-daily runs */10 UTC, self-gating)
.\.venv\Scripts\python.exe ingest\snowflake_data_pull\loader.py     # optional: refresh shared raw layer
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ② edited a view (sql/*.sql) — load seeds (stg_salesforce needs seed_salesforce_map), apply, re-run
.\.venv\Scripts\python.exe clients\client_schneider\load_seeds.py
.\.venv\Scripts\python.exe clients\client_schneider\create_views.py
gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

# ③ edited job/main.py (JSON shape) — build, deploy, run
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-export:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/job --tag $IMG --region australia-southeast1
gcloud run jobs deploy schneider-export --image $IMG --region australia-southeast1 --service-account schneider-dash-job@bidbrain-analytics.iam.gserviceaccount.com --memory 1Gi
gcloud run jobs execute schneider-export --region australia-southeast1 --wait

# ④ edited dash/dashboard.html or dash/main.py — build + redeploy the service
$IMG = "australia-southeast1-docker.pkg.dev/bidbrain-analytics/bidbrain/schneider-dash:$(git rev-parse --short HEAD)"
gcloud builds submit clients/client_schneider/dash --tag $IMG --region australia-southeast1
gcloud run services update schneider-dash --image $IMG --region australia-southeast1
```
> Don't use `gcloud builds submit --config cloudbuild.yaml` from a laptop — its deploy step fails on
> `iam.serviceaccounts.actAs`. Build the image, deploy as yourself (above). The `cloudbuild.yaml`
> files are for a future push-to-main trigger.

## Coordinates
| | |
|---|---|
| GCP project / region | `bidbrain-analytics` / `australia-southeast1` |
| BigQuery dataset | `client_schneider` (28 views + 7 CSV-loaded `seed_*` tables) |
| Data bucket / object | `bidbrain-analytics-schneider-dash` / `schneider.json` |
| Export job | `schneider-export` (runtime SA `schneider-dash-job@…`, read-only BigQuery + bucket write) |
| Web service | `schneider-dash` (runtime SA `schneider-dash-web@…`) → see [`dash/LIVE_URL.md`](dash/LIVE_URL.md) |
| Secrets | `schneider-dash-password` · `schneider-dash-session-key` |
| Refresh | Cloud Scheduler `schneider-export-daily` — `*/10` UTC, **self-gating** (rebuilds within ~10 min of new upstream data; most ticks no-op) |
| Access path | via the platform front-door — `https://dashboards.bidbrain.ai/d/schneider/` (no per-client subdomain) |

## Website (GA4) tab — SHIPPED DISABLED (built 2026-07-10, awaiting GA4 access)

A **Website** tab (GA4 whole-property web analytics) is fully built but dark until Schneider grant
read-only access. It sits behind the direct-access plan: Schneider add our account (`ian@100.digital`
or a dedicated service account) as a **Viewer** on their GA4 property — nothing else (no scheduled
reports / CSV emails).

**How it's wired** (mirrors [`client_vmch`](../client_vmch/README.md), the `perf_ga4`-based reference):
- `sql/40_stg_ga4.sql` + `sql/40b_stg_ga4_events.sql` read `raw_ga4.perf_ga4(_events)` filtered by a
  **placeholder property id** (`REPLACE_WITH_SE_GA4_PROPERTY_ID`), so every `ga4_*` view returns 0 rows
  until it is set. `sql/41-47` roll up KPI / monthly / weekly / channels / sources / key-events / daily.
- **Whole-site, no market split** — `perf_ga4` carries no country dimension (Schneider is AU/NZ, so this
  reads as AU/NZ website traffic). `total_users` / `new_users` / `page_views` / `engagement_duration`
  come back NULL from the DTS source (grain caveat) → those KPIs show `-` until a Windsor GA4 pull is added.
- `job/main.py` emits an `ga4` block + an `ga4_enabled` flag (wrapped so any GA4 issue can't break the
  CS/paid dashboard). The dashboard's global **Website** tab (`renderWebsite()`) **auto-appears only once
  `ga4_enabled` is true** (real sessions have landed) — nothing half-built shows to the client before then.

**TO ENABLE (once SE grant Viewer access + send the numeric Property ID):**
1. Replace `REPLACE_WITH_SE_GA4_PROPERTY_ID` in `sql/40_stg_ga4.sql` **and** `sql/40b_stg_ga4_events.sql`.
2. Add the property to `ingest/dts_data_pull/create_views.py` `PROPERTY_NAMES` (a commented placeholder is
   there) and **create its GA4 BigQuery Data Transfer** in the Cloud Console, then run
   `python ingest/dts_data_pull/create_views.py` so `raw_ga4.perf_ga4` picks it up.
3. `python clients/client_schneider/create_views.py` (reapply the SE views).
4. `gcloud run jobs execute schneider-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait`
   (a view/source change doesn't advance the freshness gate, so force it).
5. Redeploy the service (`dash/deploy_dash_schneider.ps1`) if the dashboard HTML changed — the Website tab
   then appears with data.
6. (Optional) once SE confirm which GA4 events count as conversions, narrow the `WHERE` in
   `sql/46_ga4_key_events_market.sql` to those event names.

## Files
- [`DASHBOARD_GUIDE.md`](DASHBOARD_GUIDE.md) — **comprehensive client-facing guide** (built from the
  client's `raw_files/` + live BigQuery): what every tab/card/number is and how it's computed, the
  campaign-ID reconciliation, and a **client-vs-dashboard gap list** (incl. the live AirSeT lead-ID
  mismatch). Written for a client review / chatbot Q&A. Start here for "how does this dashboard work".
- [`data/`](data/) — the human-editable seed CSVs (campaign map / budgets / targets / flighting /
  channel split / media plan / salesforce map), loaded to `seed_*` tables by [`load_seeds.py`](load_seeds.py).
- [`sql/`](sql/README.md) — the 30 BigQuery views (filter + CS leads + paid delivery + `cs_audience` + the GA4 Website layer `40-47`, shipped disabled).
- [`job/`](job/README.md) — the export job (stage 2): views + seed tables → `schneider.json`.
- [`dash/`](dash/README.md) — the web app (stage 3): password gate + `dashboard.html`.
- [`INTAKE.md`](INTAKE.md) — the resolved data slice + open items handed to the client.

## See also
- [Root README](../../README.md) · the [`client_STT`](../client_STT/README.md) archetype · [`snowflake_data_pull`](../../ingest/snowflake_data_pull/README.md).
