# PHASE 2 REPORT — Merge Register into Central

**Date:** 2026-07-22 · **Scope:** grid-core (The Grid) · **Playbook:** `grid-core/GRID_BUILD_PLAYBOOK.md` Phase 2

**Outcome:** ONE campaign-table tab. The Register tab is **deleted** (nav button, section,
`renderRegister`/`RCOLS`/`RGROUPS`/`RHINTS` and every helper/CSS rule only it used — removed,
not hidden). Central absorbed everything Register uniquely had and kept its full identity.
All 6 test suites pass (133 assertions, 0 failures); headless-Chrome verification against a
live `node server.js` (88 campaigns) passed every checklist item; Schneider parity across
Pulse and the merged Central is **bit-identical for all 25 rows** at a pinned as-of.

**Precondition check (required before starting): PASS.** Pulse, Register and Central all read
the live SQLite DB via `GET /api/central/campaigns` + `CentralCalc.computeRow` (88 rows); no
`const DATA` / `derive.js` path exists (`typeof derive === 'undefined'`, `src/_retired/`
untouched, nothing imports it); the `early` pace state rendered in all three tabs (Pulse
legend + slate dots, 4 early pills in Register, 4 in Central) before the merge began.

---

## What the merged tab is

**Central's structure, Register's controls.** The merged Central keeps Central's skeleton —
agency sections with **collapsible per-client summary rows (tick/untick)**, the
**CONFIG / API / DERIVED** column tagging (colored `th` + legend), **LIVE/SHEET
`metricsSource` markers** on the API cells, inline CONFIG editing (dropdowns + fill-empty
cells + needs-input tints + missing-field badges), archive, Add campaign, **Map client
(reconcile entry point)**, **Sync now**, summary cards, health chips, status-view chips,
and the **media-plan reader dropzone** — and adds, from Register:

- a **Columns bar**: `Core (locked) / Pacing / Budget / Margin / Performance / Links` —
  the whole table (headers, rows, summary rows, colspans) responds to the toggled set,
  exactly as Register behaved. **All groups default ON** so Central's first paint shows its
  full familiar column set; toggling narrows it.
- a **Group: advertiser vs Flat** toggle. `advertiser` = Central's agency sections + client
  accordions; `flat` = one global list (rows regain their client label).
- Columns were **reordered group-contiguous** (core → pacing → budget → margin → perf →
  links, Register's arrangement) so a toggled group appears/disappears as one block. This is
  the one deliberate layout change to Central's table; no column was removed.

## Deliverable 3 — what was ported vs already duplicated

**Ported from Register (would otherwise have died with the tab):**

| # | Capability | Where it landed |
|---|---|---|
| 1 | Column-group filter bar (Core locked / Pacing / Budget / Margin / Performance / Links) | `CS.colGroups` + `activeCols()` + the Columns bar |
| 2 | Group: advertiser vs Flat | `CS.group` + `bodyHtml(rows, grouped)` |
| 3 | **Search** (Register used the top bar's box) | Central's own search input (`CS.q`), matching name/client/channel/objective/manager/KPI/job#/notes; keeps focus + caret through the repaint |
| 4 | **Manager filter** (Register used the top bar's seg) | `Manager` select in Central's filter row (`CS.mgr`) |
| 5 | **Per-campaign detail row** (click to expand every field) | caret in the campaign cell → `detailRowHtml()`: ALL columns across ALL groups (including toggled-off ones) + Objective, read-only, grouped under the six headings; toggles in place (no scroll jump), persists across repaints, collapses with its client accordion |
| 6 | **Numeric-desc-first sort** (first click on a numeric column sorts descending) | merged into Central's tri-state: first click = natural direction (numeric ▼ / text ▲) → flipped → off |
| 7 | **Sort-within-groups** (Register sorted inside each advertiser group) | a sort key now ranks rows **within each client** in advertiser mode; global ranking via Flat |
| 8 | **Header hover hints** (plain-language `title` per column) | every merged column carries a `hint`; 28/28 headers have one |
| 9 | **Pacing mini-bar** (fill = % spent, marker = % elapsed, colored by state) | inside the Pacing cell next to the pill |
| 10 | **Advertiser roll-up figures** (group header showed Σspent/Σbudget/% + pace dot) | client summary rows now also show aggregate **% Spent** and an **aggregate pace dot** (via `calc.paceBucket`) beside the existing Σ media/client spend, Σ effective budget, imp count, channel cluster |
| 11 | **Columns Register had that Central lacked**: Budget Gross, Ad-Serving rate, Ad-Serving cost (derived), Impressions, campaign Link button, Next Report | six new columns, correctly typed (config/derived/api) and grouped |
| 12 | **CSV projection/risk fields** (Pace, Needs/day, Projected total, Projected vs budget, Margin at risk, Margin estimated) | Central's CSV now exports the union of both tabs' column sets + effective margin; filename gained the as-of date (`central_<scope>_<yyyy-mm-dd>.csv`) |

**Already duplicated in Central (nothing to port):** status filters (Central's chips are a
superset — Live/Active/Paused/Not Active/Ended/All/Archived vs Register's All/Active/Paused/
Ended); CSV export itself (Central had its own; only the fields above were missing);
sortable headers with nulls-last; campaign/objective sub-line in the name cell; pace pills
incl. `Early`; the KPI-vs-goal verdict coloring (Central has its own `kpiVerdict`
view-layer classifier — thresholds differ slightly from the retired Pulse-side `classifyKpi`,
both are display-only text parsing, no engine change); client/advertiser grouping itself.

**Deliberate behavior changes on Central (called out, not silent):**
- Sorting no longer exits grouping (old Central: any sort → flat global list). Sorting now
  ranks within client groups; the Flat toggle gives the global ranking. Tri-state (third
  click clears) is kept.
- First click on a numeric column now sorts **descending** (Register's default; was
  ascending).
- The top bar's status/mgr/search/CSV controls are **hidden on the Central tab** — they act
  on Pulse and were inert-but-visible on Central; after the merge Central has its own search
  box, and two visible search boxes (one dead) on one screen would mislead. They still show
  on every other view, unchanged.
- Central's CSV `Agency` column was silently **empty** before (it read `r.agency`; DB rows
  carry `section`) — fixed while porting the CSV semantics, since "CSV export works on the
  merged tab" is this phase's deliverable.

## Deliverable 5 — draft/thin rows: EXCLUDED from Pulse (option b)

`loadSpine()` now filters `status === 'Draft'` (alongside `archivedAt`), so drafts never
reach any Pulse view, the client rail counts, or the Pulse CSV. They remain fully visible in
Central (the Live working set includes Draft; the All/status chips show them; the
needs-input tints + missing-field badges are exactly the "finish setting this up" treatment
drafts need).

**Why (b) over (a) muted-label styling:** Pulse is a decision surface — on pace / off pace /
money at risk. A draft has no dates (no pacing), no spend (no risk), no budget (no bar): it
cannot need attention, so for a buyer scanning Pulse it is pure noise with zero decision
signal, and "All" on Pulse exists to add Ended/Paused context, not setup work. Central is
where drafts legitimately live and already has the right affordances. A muted label would
still cost table rows and rail-count honesty to display rows that cannot say anything.

Nuance found while verifying: the DB has exactly **2** thin rows. `Caltex · Star Card ·
TradeDesk` (status Draft, no budget/spend) — now Pulse-excluded. `Ad Assembly · (no name) ·
TradeDesk` (status **Not Active**, budget $4,800, spend $705) — **kept** in Pulse's All view:
it is a real historical row missing a *name*, not a draft; it carries money and shows as
"(unnamed)". Central shows its name cell as "—" (name is not currently an inline-fillable
field — noted under "Not anticipated").

## Verification (headless Chrome via CDP against live `node server.js`, 88 campaigns)

Unit suites: `npm test` → **133 assertions across 6 suites, 0 failures** (calc 52, readiness
22, render-central 6, live-count 3, accordion 14, central-rebuild 31 — accordion/render
suites exercise the merged `_bodyHtml`/summary-row code directly).

| Checklist item | Result |
|---|---|
| Register tab gone from nav | nav = `[pulse, brain, central, exec]`; `#view-register` = null; `renderRegister`/`RCOLS`/`RGROUPS` undefined; fresh load of an old `#view=register` bookmark lands on Pulse |
| Merged Central renders | 41 rows (Live view) / 88 (All); 2 agency sections; 11 client summary rows; summary cards, legend, health + status chips, Add/Map/Sync/Export buttons, media-plan dropzone all present |
| Column groups switch the table | 28 headers all-on → **24** with Margin off (Plat./Camp. Margin, Ad-Serv rate+cost gone) → **10** with only Core+Pacing → 28 restored; header hints on 28/28; `th` tagging = 3 API / 17 CONFIG / 8 DERIVED |
| Group: advertiser vs Flat | Flat: 0 sections / 0 summary rows / 88 flat rows with client labels; advertiser: sections + accordions return |
| Tick/untick a client | expand → that client's 3 child rows un-hide (others stay collapsed); collapse → 0 visible; detail rows collapse with their client |
| Search works | "water": 88 → 2 rows, all matching; input keeps focus + caret through repaint; clearing restores 88 |
| CSV export works | `central_all_2026-07-22.csv`; header contains every ported column (checked all 11 by name — none missing); toast "Exported **88** rows" = 88 rows shown; Agency column now populated ("100% DIGITAL") |
| Manager filter | options `all, Ben, Julfi, Mel, Zhen`, filters rows |
| Detail rows | expand → 1 `.ct-detail` with headings Core / Pacing / Budget / Margin / Performance / Links & Notes; collapse → 0 |
| Sort behavior | first click Media Spend = ▼ (desc), sections remain (within-group sort); three clicks → sort cleared (0 active headers in the Central table) |
| **Schneider parity** | `Water and Environment · TradeDesk` at pinned as-of: spent/elapsed/effective-margin/profit-at-risk/needs-per-day/projVar/pace **all bit-equal** (risk $59,310.005783…, reqDaily $471.335855…). All **25 Schneider rows × 9 metrics: zero mismatches** |
| 'early' pace pills on merged tab | 4 render (`.ct-pace-early`), same campaigns as pre-merge; pacing mini-bars ×74 |
| Draft rows | Pulse `DATA` = **87** rows, **0** Drafts (was 88 incl. 1 Draft); Central All shows the Draft (status select = "Draft", id `cmp-904b72f787ac`) |
| Console errors | **Zero application errors.** The only console entry is the pre-existing `GET /favicon.ico → 404` (the server ships no favicon; present in the pre-merge baseline run too) |
| Other tabs unaffected | Pulse: 5 KPI cards, 32 scatter dots, early legend; Brain renders; Executive renders 12 cards |

Parity note (expected, documented in Phase 1): with **no BQ sync yet** in this DB
(`lastSyncedAt` null on all rows, LIVE markers 0 / SHEET 41), each tab anchors "as of" to
*now at its own render moment*, so live-page `pctFlightElapsed` can differ in the 6th decimal
between tabs (~seconds of flight). At display rounding it is invisible, and at a pinned as-of
the engines are bit-identical — parity is by construction (one engine, one anchor once a
sync exists).

## Files changed / deleted

**Changed**
- `grid-core/src/central/render-central.js` — the merge: column groups + Columns bar,
  Group toggle, search + Manager filter, detail rows, six new columns, group-contiguous
  reorder, header hints, pacing mini-bar, summary-row % spent + pace dot, sort defaults,
  CSV union + Agency fix + dated filename, injected CSS for all of it. Guard added so a
  same-named derived column (`adServingCost`) can never inherit the needs-input editable
  treatment (`NEEDS_INPUT` itself untouched).
- `grid-core/the-grid.html` — Register nav button, `#view-register` section, the whole
  Register JS block (11,253 chars) and its CSS **deleted**; retired-with-it helpers removed
  (`money`, `pct`, `txt`, `dnum`, `sdate`, `statusCls`, `.s-*`, `.linkbtn`, `.regctl`,
  `tr.grp`, `.pacecell`, `tr.detail` etc.; `.chip-t` kept — the Pulse Labels toggle uses it);
  `F.cols/group/collapsed/expanded` state + 11 `.clear()` call sites removed; `segGroup` +
  column-chip wiring removed; `renderTableOnly` now Pulse-only; hash whitelist drops
  `register`; **Draft exclusion in `loadSpine()`**; top-bar controls hidden on the Central
  view; comments/banner updated ("Pulse and Central read the live DB").
- `grid-core/README.md` — Phase-2 block added; nav lists and "Pulse/Register" phrasing
  updated; Draft-exclusion noted.
- `grid-core/package.json` — description updated.

**Deleted (code, not files):** Register's entire tab. No files were deleted; no file remains
that only Register used. `calc.js` untouched (frozen this phase — verified byte-identical to
pre-phase; only its consumers changed).

**Not updated, deliberately:** `GRID_BUILD_PLAYBOOK.md` (the referee/audit document — its
live framing already reads "Central (absorbs Register)"; its phase prompts are historical)
and `GRID_INVENTORY.md` (the frozen pre-Phase-1 inventory, already superseded by the
PHASE*_REPORTs which later phases are told to read; Phase 4's cleanup pass is the right
place if planning wants it rewritten).

## Not anticipated (reported, NOT fixed)

1. **Likely duplicate row in the sheet import.** Schneider has THREE
   `Software First EcoStruxure · Linkedin` rows; two (`cmp-e2686e30a90d`,
   `cmp-c59c8e0abec4`) are identical on name/channel/start/end (2026-07-09 → 2026-09-30).
   Phase 1's diff had flagged "×2 (newer sheet vintage)"; it is actually ×3 with an
   exact-key twin pair — that smells like one real duplicate in `central-import.json` /
   the source sheet. Data issue, out of scope; surfaced here for planning (archive one in
   the UI if confirmed).
2. **`favicon.ico` 404** on every page load (server serves no favicon). Pre-existing —
   present in the pre-merge baseline run — and browser-initiated, not app code. One static
   file or a 204 route in `server.js` silences it; left for Phase 4 cleanup.
3. **Campaign NAME is not an inline-fillable field in Central.** The unnamed-but-real
   `Ad Assembly` row shows "—" in the name cell with no fill-empty affordance (`name` is not
   in `NEEDS_INPUT`, and the missing-fields badge doesn't count it). If planning wants
   unnamed rows repairable from the UI, that's a small follow-up — not changed this phase.
4. **Manager-filter asymmetry:** Pulse's top-bar manager seg deliberately filters out
   `Julfi` (`buildMgrSeg` has an explicit exclusion); Central's new Manager filter is built
   from the data and includes Julfi (2 campaigns carry the name). I did not replicate the
   Pulse-side exclusion in Central — the full-truth table showing all real values seems
   right — but flagging the inconsistency since the Pulse hack presumably has a reason.
5. **Headless-verification tooling note** (environment, not app): repeated headless-Chrome
   CDP sessions on this machine intermittently hang at startup; a watchdog + rerun was
   needed. No bearing on the Grid itself.

## Checkpoint 2 — how to verify by hand

1. `cd grid-core && node server.js` → `http://localhost:8787/the-grid.html`. Nav shows
   Pulse · Brain · Central · Executive — no Register.
2. Central: toggle Pacing → Margin → Performance chips (columns respond as one block);
   switch Group: advertiser ↔ Flat; expand/collapse a client; click a campaign's caret for
   the full-detail row.
3. Type in Central's search box; pick a Manager; press Export CSV and open the file (note
   the Needs Per Day / Projected / Margin At Risk columns and the as-of date in the name).
4. Pick any Schneider campaign and compare % spent / profit at risk between Pulse and
   Central — identical (pre-first-sync, % elapsed can differ by seconds' worth in the far
   decimals; see the parity note).
5. Central → status chip "All": the slate `Early` pills render; the Caltex Draft row is
   here — and absent from Pulse's All.
