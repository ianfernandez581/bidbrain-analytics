# PHASE 1 REPORT — Spine unification + the TTD margin rule

**Date:** 2026-07-22 · **Scope:** grid-core (The Grid) · **Playbook:** `grid-core/GRID_BUILD_PLAYBOOK.md` Phase 1

**Outcome:** Pulse and Register now read the live SQLite DB through `src/central/calc.js`
(the same pipe Central uses). The baked `const DATA` literal, the inline engine in
`the-grid.html`, `src/derive.js` and `build_grid_data.py` are retired. The per-channel
effective-margin rule exists in code for the first time, with unit tests. All existing
test suites pass (39 new + 22 + 6 + 3 + 14 + 31, zero failures). The Schneider old-vs-new
diff has **zero unexplained differences**.

---

## Deliverable 2 — Formula reconciliation table

Three formula sites existed, not two (see "Not anticipated" #1): `src/derive.js`,
`src/central/calc.js`, **and a third inline engine in `the-grid.html`** (`derive()` /
`recommend()`, the code Pulse actually ran). The table covers all three. "Survivor"
is what `calc.js` computes now.

| # | Formula | derive.js | the-grid.html inline | calc.js (old) | **SURVIVOR (calc.js now)** | Why |
|---|---|---|---|---|---|---|
| R1 | % budget spent | `clientSpent / totalBudget` | baked sheet cell (same def) | `clientSpend / effectiveBudget` | **`clientSpend / effectiveBudget`** (budgetGross first, else totalBudget) | Budget tracking is on the client-billed basis; some rows carry the media budget in totalBudget and the client budget in budgetGross. Central already shipped this definition — changing Central's live numbers silently would be worse. |
| R2 | Budget remaining | `totalBudget − clientSpent` | baked cell (same) | `effectiveBudget − clientSpend` | **`effectiveBudget − clientSpend`** | Same base as R1 — remaining must subtract from the same budget % spent divides by. |
| R3 | % flight elapsed | `MIN(x, 1)` — **no lower clamp** (negative pre-flight), `asOf` param | baked cell + hardcoded `SNAP=2026-07-08` for day math | `clamp(x, 0..1)`, `today` param | **`clamp(0..1)`**, anchored to the DB's newest `lastSyncedAt` (`latestSyncAsOf`) | A pre-flight campaign is 0% elapsed, not −4%. The as-of anchor now moves with the data instead of a baked date (Deliverable 5). |
| R4 | Pacing band | ratio band **±0.10** (`paceState`) | **gap band ±0.15** (`pctSpent − pctElapsed`) | ratio **>1.05 Over / <0.95 On** | **ratio 1.05/0.95** (`pacingStatus`, new lowercase twin `paceBucket`) | The three could disagree on the same row. calc.js's band is what Central has been showing live; Pulse must match Central to the digit, so Pulse adopts it. Consequence: the band is tighter → more rows flag (Schneider: 12 rows moved from "ok" to over/under, all tagged R4 in the diff). The scatter's green region is now the ratio **wedge** around the diagonal, so dot colours and the shaded band still agree. |
| R5 | CPM performance | `clientSpent/imps×1000` | baked cell (same def) | `mediaSpend/imps×1000` | **`mediaSpend/imps×1000`** | The media-buyer's CPM, on the SAME basis as Forecast CPM — comparing a client-billed CPM to a media-cost forecast overstated CPMs by the margin multiple (e.g. LiquidAI TTD $16.23 → $6.49). |
| R6 | Margin used for profit-at-risk | `campaignMargin` clamped 0..1, else **0.60 assumed** (`revenueAtStake`) | `campaignMargin` if >0.001, else 0.60 | — (absent) | **Effective margin per channel** — see Deliverable 1 below | The money rule. Never one blended formula. |
| R7 | Profit/margin-at-risk formula | gap-based: `|pctSpent−pctElapsed| × totalBudget × margin`, off-pace rows only | **projection-based: projected shortfall × margin**; `atStake` = shortfall-risk or overrun $ | — (absent) | **Ported the inline (projection) definition** → `profitAtRisk` / `atStake` | The projection definition is what Pulse displayed and what the attention queue sorts by; derive.js's gap variant was never rendered anywhere. Ported 1:1 with the budget base switched to effectiveBudget (R1) and the margin switched to the effective-margin rule (R6). |
| R8 | Ad-serving cost | `null` when rate/imps missing | baked sheet cell | `0` when no rate | **`0` when no rate or no imps** (unchanged calc.js) | A campaign with no ad-serving rate has zero ad-serving cost, not unknowable margin. |
| — | Pacing projections (`runRate`, `projTotal`, `projVar`, `projState` ±5% band), **needs-$/day** (`reqDaily`), day counts, `recommend()` action text | absent | **only here** | absent | **Ported 1:1** → `pacingProjection()`, `pacingAction()` | Pulse needs them; calc.js is now the single complete engine. Same rounding (`Math.round` day counts), same thresholds (3×/1.5×/1.1×/0.8×), same PROJ_BAND 0.05. |
| — | `grossUpClientSpend` (derive.js) | `mediaSpend/(1−margin)` | — | — | **not ported** | Superseded by the sync's `spendMult` rule in `db.syncCampaignMetrics` (clientSpend = mediaSpend × spendMult; never silently grossed). |

Also retired with the inline engine: hardcoded `SNAP`, `PACE_BAND`, `PROJ_BAND`,
`MARGIN_MIN` constants in the-grid.html (`ASSUMED_MARGIN` now read from `CentralCalc`).
`classifyKpi`/`classifyCpm` (KPI-text vs goal chips) stay in the view layer — they are
presentational text parsing, present in neither engine, and unchanged.

---

## Deliverable 1 — The margin rule (in `src/central/calc.js`)

`marginRuleFor(channel)` + `effectiveMargin(c, d)`:

- **TradeDesk, DV360** (regex also matches "Trade Desk", "TTD", "Display & Video 360") → **Platform Margin**.
- **Google Ads, Meta, LinkedIn, Reddit, and any other channel** (DOOH, LINE, null, …) → **Campaign Margin** (realized).
- `profitAtRisk` and `atStake` multiply against the effective margin per channel — never a blended formula. Ad-serving cost remains its own line (inside `campaignMargin` via the derived `adServingCost`).

**Documented degrade behavior (deliberate, loud, never silent):**

- Platform-margin channel with `platformMargin` missing, **0, or ≥1** → falls back to the realized campaign margin when usable, else `ASSUMED_MARGIN` (0.60), and **always** sets `marginWarning='platform-margin-missing'`. The UI renders the estimated treatment (~value, `est`/`plat?` chip with an explanatory tooltip, "set margin" nudge in the queue). `platformMargin=0` counts as missing because the sheet writes 0 as filler and a ×0 multiplier would silently zero profit-at-risk — exactly the failure the rule exists to prevent.
- Campaign-margin channel with no usable realized margin (null or ≤0.001) → `ASSUMED_MARGIN`, `effectiveMarginSource='assumed'` (the legacy "est." chip behavior, kept).

**Unit tests** — `src/central/calc.test.js`, 39 assertions, all passing, wired into `npm test`:

| Mandated case | Result |
|---|---|
| TTD row (platformMargin 0.45, realized 0.60) | uses **0.45** platform margin; profit-at-risk = shortfall × 0.45 ✓ |
| DV360 row (platformMargin 0.5) | uses platform margin ✓ |
| Google Ads row | uses realized campaign margin 0.60 ✓ |
| platformMargin **present** but channel = Meta | uses **campaign** margin (0.60, not the 0.9 platform value) ✓ |
| TTD row **missing** platformMargin | `marginWarning='platform-margin-missing'` set; falls back realized→assumed as documented; PM=0 treated as missing ✓ |

Plus projection math (hand-checked 60-day fixture), overrun `atStake`, `paceBucket` band
consistency with `pacingStatus`, effectiveBudget base, and `latestSyncAsOf`.

**Live hand-check on Schneider rows** (asOf pinned 2026-07-07):

- `Water and Environment · TradeDesk`: platformMargin 0.6, realized 0.6108 → effectiveMargin **0.6000 (source: platform)**; projVar −97,096 → profitAtRisk **58,258**.
- `Advancing Energy T · Google Ads`: realized 0.0050 → effectiveMargin **0.0050 (source: campaign)** — platform margin ignored on a campaign-rule channel.
- `EBA · TradeDesk`: platformMargin 0.9729 wins over realized 0.6557 (source: platform).
- `Water and Environment · Linkedin`: realized 0.0000 (unusable) → **0.60 assumed**, flagged `est`.

---

## Deliverable 3 — Schneider before/after diff

Script: **`grid-core/scripts/compare_pulse_paths.js`** (re-runnable: `node scripts/compare_pulse_paths.js [--all]`).
OLD path = the frozen baked literal (`grid-core/test-fixtures/pulse-legacy/const-data-2026-07-08.json`)
+ a verbatim replica of the legacy inline engine at `SNAP=2026-07-08`. NEW path = SQLite
(seeded exactly like server boot) + `calc.computeRow()` **pinned to the same as-of**, so no
difference can come from the calendar. Every differing metric is mechanically classified by
replaying the OLD formula on the NEW inputs:

- **FORMULA (Rn)** — replay reproduces the old value → the difference is exactly one reconciliation-table row;
- **INPUT-DRIFT** — the raw inputs differ (`const DATA` was generated from an older vintage of Central2.xlsx than `central-import.json`; 83 vs 85 sheet rows, 23 vs 25 Schneider rows);
- **BAKED-ARTIFACT** — the old sheet CELL disagrees with its own row's inputs (Excel blank-as-zero artifacts like `campaignMargin=1.0` with no media spend, or stale cells like LiquidAI LinkedIn CPM 18.16 vs its own V/T = 17.18);
- **UNEXPLAINED** — a bug (script exits 1).

**Result: SAME=92 · FORMULA=16 · INPUT-DRIFT=41 · BAKED-ARTIFACT=12 · UNEXPLAINED=0.**

The 16 FORMULA differences by rule: **R4** (pacing band, 12 rows — e.g. `Ent IT · TradeDesk`
ok→over at ratio 1.06; `LiquidAI · TradeDesk` ok→under at 0.55), **R5** (CPM basis, 3 rows —
`Ent IT · TradeDesk` 16.71→6.68, `LiquidAI · TradeDesk` 16.23→6.49, `NEL · TradeDesk`
73.88→29.55), **R3** (pre-flight clamp, 1 row — `DOOH` elapsed —→0). Representative
INPUT-DRIFT: `Water and Environment · TradeDesk` profit-at-risk 59,037→58,342 (mediaSpend
vintage 2,172→842; both engines multiply by the same 0.60 effective margin). Two
`Software First EcoStruxure · Linkedin` rows exist only in the newer DB vintage.

<details><summary>Full per-campaign diff (23 old × 25 new Schneider rows)</summary>

```
scope: Schneider · both paths pinned as-of 2026-07-07

▸ Advancing Energy T · Google Ads (Active)   input drift: clientSpend —→38.19 | mediaSpend —→38 | impressions —→377 | budgetGross —→11,000
    % spent —→0.0035 INPUT-DRIFT · % elapsed —→0.0042 BAKED-ARTIFACT · pace none→under INPUT-DRIFT
    profit-at-risk —→24.90 INPUT-DRIFT · needs$/day —→70.27 INPUT-DRIFT · CPM —→101 INPUT-DRIFT
▸ Advancing Energy T · Linkedin (Active)     input drift: clientSpend 804→1,121 | mediaSpend 804→1,121 | imps 33,164→44,828
    % spent .0212→.0295 INPUT-DRIFT · pace ok→under FORMULA R4 · risk 9,780→4,639 INPUT-DRIFT
    needs$/day 238→236 INPUT-DRIFT · CPM 21.69→25.01 INPUT-DRIFT
▸ Airset · Linkedin (Active)                 input drift: clientSpend 1,638→1,769 | mediaSpend 1,638→1,769 | imps 49,784→52,407
    % spent .1311→.1415 INPUT-DRIFT · pace ok→over FORMULA R4 · risk 109→— INPUT-DRIFT
    needs$/day 61.71→60.97 INPUT-DRIFT · CPM 30.22→33.76 INPUT-DRIFT
▸ Airset · TradeDesk (Active)                input drift: mediaSpend 2,650→995
    pace ok→over FORMULA R4 · CPM 24.72→9.21 INPUT-DRIFT
▸ DOOH · DOOH (Not Active)
    % elapsed —→0 FORMULA R3 (pre-flight clamp) · margin 0→— BAKED-ARTIFACT
▸ EAE Consideration · DV360 (Ended)
    pace ok→under FORMULA R4 · margin 1.0→— BAKED-ARTIFACT (blank mediaSpend baked as margin=100%)
    risk 1,609→965 BAKED-ARTIFACT
▸ EAE Conversion · DV360 (Ended)
    margin 1.0→— BAKED-ARTIFACT · risk 1,483→890 BAKED-ARTIFACT
▸ EBA · TradeDesk (Active)                   input drift: mediaSpend 8,597→2,960
    pace ok→over FORMULA R4 · margin .97→.6557 INPUT-DRIFT · CPM 1.22→0.49 INPUT-DRIFT
▸ Ent IT · Linkedin (Active)                 pace ok→over FORMULA R4
▸ Ent IT · TradeDesk (Active)                input drift: clientSpend 19,970→20,636 | mediaSpend 7,988→8,254 | imps 1,194,734→1,236,459
    % spent .3325→.3436 INPUT-DRIFT · pace ok→over FORMULA R4 · needs$/day 349→343 INPUT-DRIFT
    CPM 16.71→6.68 FORMULA R5
▸ IA Services · Linkedin (Not Active)        input drift: status Not Active→Ended
    pace ok→under FORMULA R4 · margin 1.0→— BAKED-ARTIFACT · risk 1,985→1,191 BAKED-ARTIFACT
▸ Industrial Edge W3 Prefab · Linkedin       input drift: clientSpend —→287 | mediaSpend —→287 | imps —→31,571 | budgetGross —→9,150
    % spent 0→.0314 INPUT-DRIFT · pace ok→under FORMULA R4 · risk —→1,751 INPUT-DRIFT
    needs$/day —→61.12 INPUT-DRIFT · CPM —→9.09 INPUT-DRIFT
▸ Industrial Edge W3 Prefab · TradeDesk      input drift: startDate 2026-07-01→— (dropped in the newer sheet)
    % spent 0→— BAKED-ARTIFACT · % elapsed .0461→— INPUT-DRIFT · pace ok→none INPUT-DRIFT · margin 0→— BAKED-ARTIFACT
▸ LiquidAI · Linkedin (Active)
    CPM 18.16→17.18 BAKED-ARTIFACT (old cell disagrees with its own V/T)
▸ LiquidAI · TradeDesk (Active)              input drift: clientSpend 10,455→10,913 | mediaSpend 4,182→4,365 | imps 644,215→672,211
    % spent .1958→.2044 INPUT-DRIFT · pace ok→under FORMULA R4 · risk 4,535→3,331 INPUT-DRIFT
    needs$/day 244→241 INPUT-DRIFT · CPM 16.23→6.49 FORMULA R5
▸ NEL · Linkedin (Active)                    input drift: clientSpend 3,996→3,406 | mediaSpend 3,996→3,406 | imps 97,035→84,347
    % spent .148→.1261 INPUT-DRIFT · pace ok→under FORMULA R4 · risk 3,147→5,075 INPUT-DRIFT · needs$/day 288→295 INPUT-DRIFT
▸ NEL · TradeDesk (Active)                   input drift: clientSpend 1,057→1,037 | mediaSpend 1,057→415 | imps 14,306→14,042
    margin .081→.5997 INPUT-DRIFT · risk 345→2,594 INPUT-DRIFT · CPM 73.88→29.55 FORMULA R5
▸ Software First EcoStruxure · Linkedin      input drift: totalBudget —→13,000 | budgetGross —→13,000 | start —→2026-07-09 | end 2026-09-30→2026-10-31 | status —→Active
    % elapsed .9982→0 INPUT-DRIFT · margin 0→— BAKED-ARTIFACT
▸ Software First EcoStruxure · TradeDesk     input drift: clientSpend 1,763→2,596 | mediaSpend 663→855 | imps 259,747→315,227
    % spent .1336→.1967 INPUT-DRIFT · margin .1555→.6708 INPUT-DRIFT · risk 682→184 INPUT-DRIFT
    needs$/day 136→126 INPUT-DRIFT · CPM 7.06→2.71 INPUT-DRIFT
▸ Water and Environment · Linkedin (Active)  input drift: clientSpend 2,461→2,421 | mediaSpend 2,461→2,421 | imps 14,304→13,912
    pace ok→over FORMULA R4 · needs$/day 31.84→32.01 INPUT-DRIFT
▸ Water and Environment · TradeDesk (Active) input drift: mediaSpend 2,172→842
    risk 59,037→58,342 INPUT-DRIFT · CPM 6.21→2.44 INPUT-DRIFT

summary: SAME=92 FORMULA=16 INPUT-DRIFT=41 BAKED-ARTIFACT=12 UNEXPLAINED=0
rows only in the NEW DB: Software First EcoStruxure · Linkedin ×2 (newer sheet vintage)
```
</details>

---

## Deliverable 4 — The switch (verified rendering)

`the-grid.html` boots by fetching `GET /api/central/campaigns`, filtering archived rows,
and mapping each DB row through a new `spineRow()` adapter (DB names → the grid row shape
the views always consumed) with **all derived fields from `CentralCalc.computeRow()`** —
nothing is computed in the HTML any more. Register reads the same rows, so it re-piped
automatically. Central is unchanged except its `computeRow` is now anchored to the same
as-of (`latestSyncAsOf`) as Pulse, so once a sync exists **all three tabs compute from the
identical rows, engine and timestamp** — parity by construction, not by coincidence.
(Until the first sync both anchor to "now" at render time; sub-minute skew, invisible at
display rounding.)

Verified in headless Chrome against a live `node server.js` (88 campaigns seeded):
KPI cards ×5, scatter ×32 dots with the ratio-wedge on-pace region, attention queue ×12
sorted by money at risk (with `est`/`set margin` treatments), "Wrapping up soon" 9 rows
(14-day window), by-advertiser roll-up ×10, clients/campaigns table, all filters and the
CSV export (filename date now = as-of). Register: 88 rows, 15 advertiser groups, column
groups + Flat/advertiser toggle. Central intact. Zero console errors.

One found-and-fixed integration bug: `calc.js` loads as a classic script, so its new
top-level `const ASSUMED_MARGIN` collided with the page's global lexical scope and killed
the whole inline script. `calc.js` is now wrapped in an IIFE (exports only
`window.CentralCalc`), which also stops `DAY_MS` etc. leaking.

## Deliverable 5 — Retirement

- **`const DATA` literal (56,828 chars) removed** from `the-grid.html`; frozen as the comparison fixture `grid-core/test-fixtures/pulse-legacy/const-data-2026-07-08.json` (Phase 4 may delete once the safety net is no longer wanted).
- **Inline `derive()`/`recommend()` engine removed**; `SNAP`, `PACE_BAND`, `PROJ_BAND`, `MARGIN_MIN` constants gone.
- **`src/derive.js` + `src/derive.test.js` quarantined** → `src/_retired/` with a QUARANTINED header. **Nothing imports derive.js**: `src/reconcile.js` now exits loudly at the top (retired CLI), `src/orchestrator.js`'s import replaced with a throwing stub (the layer is dormant; no connector work done — the throw just prevents silent revival with retired formulas). `package.json` test/check scripts updated.
- **`scripts/build_grid_data.py` marked RETIRED** — retirement header + a `sys.exit` kill switch before any import (the literal it rewrote no longer exists; running it would have corrupted the-grid.html). Phase 4 deletes. (`scripts/live_metrics.py` was only ever invoked from inside a build run, so it is dormant by extension — left for Phase 4.)
- **Hardcoded SNAP dependency removed.** Pacing "as of" = `calc.latestSyncAsOf(rows)` (newest `lastSyncedAt` in the DB). Fallbacks are **loud**: no sync ever → amber banner across the content area + amber sidebar badge "No sync yet — as of now"; server unreachable → red banner ("start node server.js") + red badge, and nothing renders rather than stale numbers. The sidebar badge shows the real sync timestamp otherwise (amber again if >3 days old). The old "Snapshot 29 Jun" hardcoded caption is gone.

## Files changed / added / retired

**Changed**
- `grid-core/src/central/calc.js` — margin rule, ported Pulse formulas, `latestSyncAsOf`, IIFE wrap, doc header
- `grid-core/the-grid.html` — const DATA → live-spine loader (`spineRow`/`loadSpine`), inline engine removed, ratio-wedge scatter band, 3 gap-band call sites → `paceBucket`, loud as-of badge + `#spineBanner`, async boot, CSV filename, margin-warning chips
- `grid-core/src/central/render-central.js` — computeRow anchored to `latestSyncAsOf` (same as Pulse)
- `grid-core/src/brain/db.js` — new derived fields added to `CENTRAL_DERIVED_FIELDS` (write-rejection, defense in depth)
- `grid-core/src/orchestrator.js` — derive.js import → throwing stub (dormant layer, no other change)
- `grid-core/src/reconcile.js` — retired: loud exit at top
- `grid-core/scripts/build_grid_data.py` — retired: header + kill switch
- `grid-core/package.json` — test/check scripts + description
- `grid-core/README.md` — spine/formula/engine sections updated to what is now true (orchestrator/connector claims deliberately left for Phase 4 per the playbook)

**Added**
- `grid-core/src/central/calc.test.js` — margin-rule + ported-formula tests (39)
- `grid-core/scripts/compare_pulse_paths.js` — the Deliverable-3 safety net (re-runnable)
- `grid-core/test-fixtures/pulse-legacy/const-data-2026-07-08.json` — frozen legacy baked data
- `PHASE1_REPORT.md` (this file)

**Retired / quarantined**
- `grid-core/src/derive.js` → `grid-core/src/_retired/derive.js`
- `grid-core/src/derive.test.js` → `grid-core/src/_retired/derive.test.js`

## Things this playbook did not anticipate (reported, NOT fixed)

1. **There were three formula engines, not two.** Pulse never imported `src/derive.js` in the browser — it rendered baked derived fields plus a third inline engine in `the-grid.html` (`derive()`/`recommend()`), whose definitions differed from BOTH named engines (gap-band ±0.15 pacing; projection-based profit-at-risk that derive.js lacked). The reconciliation table covers all three; the inventory's "two formula engines" framing was incomplete.
2. **The baked data and the DB import were different sheet vintages.** `const DATA` (83 rows) vs `config/central-import.json` (85 rows) — 41 of the Schneider metric differences are pure input drift, including materially different mediaSpend on TTD rows (e.g. EBA 8,597→2,960). Anyone hand-checking Pulse against memory of the old numbers will see changes that are data vintage, not formulas.
3. **The old sheet carried self-inconsistent baked cells** (12 found in Schneider alone): `campaignMargin=1.0` on rows with blank media spend (Excel blank-as-zero), `pctSpent=0` for blank spend, a CPM cell that disagrees with its own row's spend/impressions (LiquidAI LinkedIn 18.16 vs 17.18). The new engine returns "—" (guarded null) or the recomputed value instead. These will read as "numbers changed" but the old numbers were artifacts.
4. **Pulse/Register no longer work from `file://`** — they need `node server.js` running (Central already did). The failure is loud (red banner naming the command), but the "open the HTML file directly" workflow is gone by design.
5. **`spendMult` vs the client-billed sheet values:** several Schneider LinkedIn rows show old clientSpent ≠ new clientSpend with identical media spend, because the newer import recomputed the billed figure. Once a real BQ sync runs, `clientSpend = mediaSpend × spendMult` will move these again for validated clients. Expected, but worth knowing before Checkpoint 1's eyeball pass.
6. **The tighter R4 band reshapes the attention queue.** With ratio 0.95/1.05 (vs gap ±0.15), 31 of 39 active campaigns currently flag under/over ("Off budget 32" on the KPI strip). This is Central's long-standing definition now applied consistently — but given the standing "don't cry wolf" preference, planning may want a deliberate look at whether 0.95/1.05 is the band the agency actually wants (changing it would be ONE constant in calc.js, applied everywhere at once).
7. **Draft/thin rows now reach Pulse's "All" status filter** (they were absent from the baked data). They render as "(unnamed)"/dash rows with null metrics under All; the default Active view is unaffected.
8. **`better-sqlite3` was not installed locally** (`npm ci` had never been run on this machine + npm blocked its install script pending `npm approve-scripts`). Dev-environment note, not a code issue.

## Checkpoint 1 — how to verify by hand

1. `cd grid-core && node server.js` → open `http://localhost:8787/the-grid.html`. Pulse renders: scatter, queue, roll-ups (screenshot-verified in this session).
2. Schneider in Pulse vs Central: same rows, same engine, same as-of anchor — spot-check `% spent` / margins on any Schneider campaign across both tabs.
3. TTD vs Google margin hand-check: Water & Environment TradeDesk risk = shortfall × **0.60 platform margin** (58,258 at the pinned date); Advancing Energy T Google uses its realized campaign margin.
4. Every Schneider diff: this report §Deliverable 3 (or re-run `node scripts/compare_pulse_paths.js`).
5. As-of is live: sidebar shows "No sync yet — as of now" (amber) until the first sync; after a Central "Sync now" it shows the real timestamp. Stop the server and reload → red "Live data unavailable" banner. No `2026-07-08` anywhere.

---

## Addendum (2026-07-22, post-Phase-1 micro-patch per planning)

**Pacing band widened 0.95/1.05 → 0.90/1.10** — resolves finding #6. The band is now the
named pair `PACE_BAND_UNDER`/`PACE_BAND_OVER` in `calc.js`, read by `pacingStatus`,
`paceBucket`, the Pulse scatter wedge and (via `paceBucket`) the Off-budget KPI count —
one constant, applied everywhere. R4 in the reconciliation table now reads "ratio
0.90/1.10". Tests updated (42 pass); the Schneider comparison reclassified as expected
(FORMULA 16→9, SAME 92→99, **UNEXPLAINED still 0**).

Effect on active campaigns (39, sheet-vintage data, pre-first-sync): flagged
**32 → 31** (30 under / 1 over). Only **Gateway · Gateway Project · Meta** (ratio 0.914)
dropped off the attention list. The widen barely moves the count because the remaining
flags are not band-edge cases — ratio distribution of the still-flagged: 9 below 0.3,
1 at 0.3–0.5, 8 at 0.5–0.7, 12 at 0.7–0.9, 1 over. These read as genuinely behind-pace
rows (or stale sheet spend awaiting the first BQ sync), not a band-width artifact.
Nearest to the edge if planning ever widens again: ResetData Always On Google 0.806,
Schneider Ent IT TTD 0.838 / LinkedIn 0.871, VMCH Retirement Living 0.875, Schneider
W&E LinkedIn 0.875, PropTrack Banking ABM LinkedIn 0.892.

## Addendum 2 (2026-07-22, second micro-patch): early-flight suppression

Below **15% flight elapsed** the pacing ratio is noise (10% elapsed / 5% spent is a
divide-by-almost-zero, not a "too slow" campaign), so pacing is now deliberately **not
judged** there: `PACE_EARLY_FLIGHT_THRESHOLD = 0.15` in `calc.js`; `pacingStatus` returns
**`Early`** and `paceBucket` **`early`**. Early rows are excluded from the attention
queue and the Off-budget KPI, and render as muted slate (#7E93AD) dots/pills with their
own legend entry ("Early in flight (not judged)") in Pulse, Register and Central.
Tests: 52 pass (early-regardless-of-ratio at 10%, judged-normally at 20%, boundary 0.15
judged, pre-flight elapsed=0 → early). Comparison: still **zero UNEXPLAINED** (three old
pace calls reclassified, expected).

Impact on the 39 active campaigns (still pre-first-sync sheet data):
**early=4 · under=27 · over=1 · ok=1 · none=6** — flagged count 31 → 28. Flipped
under → early: `Schneider · Advancing Energy T · Linkedin` (12.4% elapsed),
`Schneider · Advancing Energy T · Google Ads` (9.6%), `Schneider · Industrial Edge W3
Prefab · Linkedin` (13.9%). Spot-check of the remaining unders confirms they are real
signals — all well past the threshold with materially low spend: LiquidAI LinkedIn
(37% elapsed / 11% spent, $15.5k of $144.2k), Water & Environment TTD (27% / 2%, $2.2k
of $106.8k), Cloudflare Q3 Core DG LinkedIn (23% / 3%, $2.0k of $61.0k).

**Band recommendation: KEEP 0.90/1.10 — do not retune yet.** (1) The remaining flags
are deep misses (ratios 0.07–0.84), not band-edge cases; no defensible width absorbs
them. (2) The current data systematically overstates under-pacing: spend is frozen at
the ~2026-07-08 sheet vintage while the as-of fallback anchors elapsed to *now*, so
every ratio drifts down ~2 weeks' worth — tuning the band on this would overfit a
distortion the amber "No sync yet" banner already warns about. Re-evaluate after the
first real BQ sync; if a cluster then sits at 0.80–0.90, consider an asymmetric widen
of the under side only (over at 1.10 is rarer and costlier, keep it tight).
