# THE GRID — Phased Build Playbook

**Owner:** you (media buyer / developer, 100% Digital + Transmission)
**Executor:** Claude Code sessions in VS Code (one session per phase)
**Referee:** this document. If a session's work disagrees with this document, the document wins.

---

## How to use this playbook

1. Work the phases **in order**. Never start a phase before the previous phase's checkpoint passes.
2. Each phase = **one fresh Claude Code session**. Paste that phase's prompt verbatim. Fresh sessions prevent context drift.
3. Every prompt tells the session to read `grid-core/GRID_INVENTORY.md` first and to write a completion report. **Bring the completion report back to your planning conversation before starting the next phase.**
4. If a session wants to do something this playbook marks OUT OF SCOPE, the answer is no. Stop the session, note what it wanted, raise it in planning.
5. You (the human) own every checkpoint. A checkpoint is not "the code says done" — it is "you looked at real numbers and they are right."

---

## North Star (read before every phase)

The Grid is the agency's single cockpit above the 11 client dashboards. Five surfaces, each answering one question, all fed by **one** source of truth:

| Surface | Question it answers |
|---|---|
| **Pulse** | What's on pace / off pace right now, and where is money at risk? |
| **Central** (absorbs Register) | The row-level truth of every campaign — the automated `central.xlsx` |
| **Executive** | Is each client winning on their ONE headline KPI? (replaces Dashboards tab) |
| **Brain** | What should we do about it? (**PARKED** — stays mock until spine is real) |

**The trust contract:** every number is CONFIG (typed/approved), API (synced from platform truth), or DERIVED (computed fresh by one engine). Never a stale hardcoded cell. Pulse, Central, and Executive must agree to the digit because they read the same spine.

**GCP North Star:** BigQuery is the actuals layer. SQLite is the operational store (config, provenance, approvals) — a deliberate placeholder for a future BigQuery-native/Cloud SQL operational store when the Grid folds into Bidbrain. Every design decision prefers the option that survives that move.

**Keep the seam clean for Bidbrain:** build general and clean (explicit data contracts, no hardcoded dates, single formula engine), but do NOT build Bidbrain internals (its Account→Client→Brand hierarchy, LLM gateway, auth) into the Grid. Integration later must be a connection job, not a rescue job.

---

## Standing rules — embedded in every prompt, listed here once

- **Survivor spine:** live SQLite DB + `grid-core/src/central/calc.js`. The baked `const DATA` + `src/derive.js` path is legacy and is being retired.
- **Margin rule (the money rule):** effective margin is **Platform Margin for TradeDesk and DV360**; **Campaign Margin for Google Ads, Meta, LinkedIn, Reddit** (and any channel without a platform-margin concept). Profit-at-risk is computed per channel against effective margin — never one blended formula. Ad-serving cost stays a separate line where it exists today.
- **Media-plan reader posture — stage + approve, launch rule:** every extraction stages with per-field provenance + confidence; **nothing writes without human commit**; writes go to **CONFIG columns only**, never API/actuals. (Post-launch relaxation for dates/budget/channel is a future decision, not now.)
- **Brain is parked:** mock recs (`brain-mock-data.js`) and the `CU-MOCK-` ClickUp stub stay as-is. The V3/V3.5 ingestion pipeline stays wired but untouched. No session builds a recommendations engine in this playbook.
- **Known debt, do not "fix" casually:** the `orchestrator.js` live-API layer is dormant and 4 of 6 connectors (meta/dv360/linkedin/reddit) do not exist as files despite the README. Actuals come via BQ sync, not the orchestrator. Phase 4 corrects the README; nobody builds connectors.
- **No silent behavior changes.** If a formula's output must change (e.g., the two engines' CPM definitions disagree), the change is called out in the completion report with before/after values for Schneider.

---

# PHASE 1 — Unify the spine + encode the TTD margin rule

**Goal:** Pulse and Register read the live SQLite DB through `central/calc.js`. The baked `const DATA` / `derive.js` path is retired. The per-channel margin rule exists in code for the first time. Pulse looks and feels identical.

**Why first:** until there is one spine, "accurate" has no meaning — two engines can print two different margins for the same campaign. Every later phase validates against this spine.

### Paste this prompt into a fresh Claude Code session:

```
You are executing PHASE 1 of the Grid build playbook: spine unification.

READ FIRST, before writing any code:
- grid-core/GRID_INVENTORY.md (the factual inventory of what exists)
- grid-core/src/central/calc.js and grid-core/src/derive.js (the two formula engines)
- the-grid.html sections for Pulse and Register (how they consume const DATA)
- server.js (the SQLite access layer Central already uses)

CONTEXT YOU MUST HONOR:
- The survivor spine is: live SQLite DB + central/calc.js. The baked const DATA
  + derive.js path is legacy and is being retired in this phase.
- The two engines currently disagree by design (e.g., CPM = clientSpent/impressions
  in one vs mediaSpend/impressions in the other; different pacing bands). These
  conflicts must be resolved DELIBERATELY, not silently — see Deliverable 3.
- Only Schneider is BQ-validated today. Other clients' rows in the DB may still
  carry sheet/import values — that is expected and fine for this phase; the point
  is ONE pipe, not full coverage.

DELIVERABLES, in this order:

1. MARGIN RULE IN calc.js (do this first, it's the smallest and highest-stakes):
   Add an explicit per-channel effective-margin branch:
   - TradeDesk, DV360  -> Platform Margin
   - Google Ads, Meta, LinkedIn, Reddit, and any channel without a platform
     margin -> Campaign Margin
   Profit-at-risk and margin-at-risk must compute against effective margin per
   channel. Ad-serving cost remains its own line where present. Add unit tests
   covering: a TTD row, a DV360 row, a Google row, a row with platform margin
   present but channel = Meta (must use Campaign Margin), and a row missing
   platform margin on TTD (must degrade loudly, not silently — decide and
   document the behavior).

2. FORMULA RECONCILIATION TABLE (before touching Pulse):
   Produce a table of every formula that exists in BOTH derive.js and calc.js
   where the definitions differ (CPM, pacing bands, margin, projections, any
   others you find). For each: the two definitions, which one calc.js will use
   going forward, and why. Where derive.js has a formula calc.js lacks entirely
   (Pulse needs pacing projections, margin-at-risk, "needs $X/day" math), PORT
   it into calc.js — calc.js becomes the single complete engine.

3. PULSE SAFETY NET (before the switch):
   Write a comparison script that computes, for every Schneider campaign, the
   key Pulse numbers (pacing %, % budget spent, % flight elapsed, margin,
   profit-at-risk, needs-$/day) via the OLD path (const DATA + derive.js) and
   the NEW path (SQLite + calc.js), and prints a diff. Every difference must be
   explainable by a row in the Deliverable-2 table or by the new margin rule.
   Unexplained differences are bugs — fix before proceeding.

4. THE SWITCH:
   Rewire Pulse and Register to read from the SQLite DB via calc.js (through
   server.js endpoints, same pattern Central uses). The Pulse UI must be
   visually and behaviorally IDENTICAL: same scatter (x = flight elapsed,
   y = budget spent, green diagonal, bubble size = budget remaining), same
   "What needs attention" queue sorted by money at risk, same "Wrapping up
   soon" (14-day window), same by-advertiser roll-up, same campaigns table,
   same filters. You are replacing the pipe, not the tab.

5. RETIREMENT:
   Remove the baked const DATA from the-grid.html, delete or clearly quarantine
   derive.js (if any formula is still uniquely needed, it was ported in
   Deliverable 2 — nothing may import derive.js after this phase), and mark
   build_grid_data.py as retired for app data (leave the file with a header
   comment saying so; Phase 4 handles final cleanup). Remove the hardcoded
   SNAP date dependency: pacing "as of" must come from the DB's latest sync
   timestamp, falling back loudly (visible badge, not a silent stale date) if
   no sync has run.

OUT OF SCOPE — do not touch: Brain (mock stays), the media-plan reader,
reconciling any new client, autosync scheduling, the orchestrator/connectors,
merging Register into Central (that is Phase 2 — Register keeps its own tab
this phase, just re-piped).

COMPLETION REPORT — write PHASE1_REPORT.md at repo root containing:
- The formula reconciliation table (Deliverable 2)
- The Schneider before/after diff and the explanation for every difference
- The margin-rule test results
- Exactly which files changed, which were deleted/quarantined
- Anything you found that this playbook did not anticipate (do not fix it —
  report it)
```

### CHECKPOINT 1 — you must verify by hand before Phase 2:
- [ ] Open Pulse. It looks identical to before. Scatter, attention queue, roll-ups all render.
- [ ] Schneider's numbers in Pulse match Central's numbers for the same campaigns **exactly**.
- [ ] Pick one TTD campaign (e.g., Water & Environment) and one Google campaign; hand-check profit-at-risk uses Platform Margin for the TTD row and Campaign Margin for the Google row.
- [ ] Read `PHASE1_REPORT.md`. Every Schneider diff is explained. Anything "not anticipated" goes back to planning before Phase 2.
- [ ] The pacing "as of" date is live (or loudly flagged), not `2026-07-08`.

---

# PHASE 2 — Merge Register into Central

**Goal:** one campaign-table tab. Central's structure (per-client tick/untick, CONFIG/API/DERIVED enforcement, SQLite truth) + Register's column-group filters (Core / Pacing / Budget / Margin / Performance / Links, Group-by-advertiser / Flat). Register tab disappears.

**Why now:** after Phase 1 both tabs read the same spine, so this is pure UI consolidation — the cheapest it will ever be.

### Paste this prompt into a fresh Claude Code session:

```
You are executing PHASE 2 of the Grid build playbook: merge Register into Central.

READ FIRST:
- grid-core/GRID_INVENTORY.md and PHASE1_REPORT.md
- the-grid.html sections for Central and Register

PRECONDITION (verify, and stop if false): Pulse, Register, and Central all read
the live SQLite DB via central/calc.js. There is no const DATA / derive.js path.
If this is not true, STOP and report — Phase 1 is incomplete.

DELIVERABLES:
1. Add Register's column-group filter bar to Central: Core / Pacing / Budget /
   Margin / Performance / Links, plus Group: advertiser vs Flat. The whole
   table responds to the selected group, same behavior Register has today.
2. Preserve Central's identity: per-client sections with tick/untick, the
   CONFIG / API / DERIVED column tagging visible, LIVE badge and
   metricsSource:'BQ' markers, the media-plan reader entry point, and the
   reconcile flow entry point. Nothing Central can do today may be lost.
3. Preserve anything Register uniquely had (CSV export, search, status filters
   All/Active/Paused/Ended) — port, don't drop. List each ported item.
4. Remove the Register tab from the nav. Register's route/section is deleted,
   not hidden.
5. Update any internal links or docs that referenced Register.

OUT OF SCOPE: Brain, new client reconciliation, autosync, connectors, any
formula changes (calc.js is frozen this phase).

COMPLETION REPORT — write PHASE2_REPORT.md: what moved, what was ported from
Register, screenshots/description of the merged tab, anything unanticipated.
```

### CHECKPOINT 2:
- [ ] Register tab is gone from the nav.
- [ ] On Central: switch column groups (Pacing → Margin → Performance) and confirm the table responds; toggle Group: advertiser vs Flat.
- [ ] Tick/untick a client — sections behave as before.
- [ ] CSV export and search still work.
- [ ] Numbers on the merged tab still match Pulse for Schneider.

---

# PHASE 3 — Per-client onboarding: reconcile + media-plan CONFIG seeding (repeatable)

**Goal:** convert clients from sheet-values to BQ-validated, one at a time, and seed their CONFIG (targets, KPIs, margins, objectives, flight dates) from their media plans through the stage+approve reader. This phase is a **loop you run once per client**, not a single session.

**Why a loop:** reconciliation requires your judgment (approving fuzzy name matches) and plan extraction requires your approval (stage+approve). Sessions prepare; **you** validate.

**Recommended order:** start with **Cloudflare** or **MongoDB** (well-populated in the sheet, multi-platform — a real test). Then work down by money at stake.

### Paste this prompt into a fresh Claude Code session — once per client, replacing {CLIENT}:

```
You are executing PHASE 3 of the Grid build playbook for one client: {CLIENT}.
This is a repeatable onboarding run. Your job is to PREPARE everything for
human validation — you never approve matches or commit extracted values
yourself.

READ FIRST:
- grid-core/GRID_INVENTORY.md, PHASE1_REPORT.md, PHASE2_REPORT.md
- The reconcile flow code and the media-plan reader code (locations are in the
  inventory, section 5 and 6)
- Any prior PHASE3_{OTHERCLIENT}_REPORT.md files — reuse their lessons

STANDING RULES YOU MUST HONOR:
- Media-plan extractions write to CONFIG columns only (budget, target/KPI,
  objective, flight dates, platform margin, channel). NEVER to API/actuals
  columns. Everything stages with per-field provenance + confidence and waits
  for human commit. If the reader currently has any auto-write path, disable
  it for this run and report it.
- Effective margin rule: TTD/DV360 -> Platform Margin; others -> Campaign
  Margin. Extracted margins must land in the correct field.

DO, in this order:
1. RECONCILE PREP: run the BQ name-list pull for {CLIENT}, produce the fuzzy-
   match candidate list (grid row <-> BQ campaign name, with match confidence),
   and surface it in the reconcile UI for human approval. Flag anything with
   no plausible match or multiple plausible matches.
2. STOP for human approval of matches. (The human does this in the UI.)
3. PLAN INGESTION PREP: locate {CLIENT}'s media plan file(s) — ask the human
   to provide them if not in the repo/drive path. Run them through the reader.
   Produce the staged extraction: every field with source location in the plan
   + confidence. Flag missing fields (no forecast CPM found, no margin stated,
   ambiguous KPI wording) rather than guessing. Map objectives/KPIs onto the
   existing controlled vocabulary; if a plan uses wording that doesn't map,
   flag it — do not invent a new category.
4. STOP for human review + commit of the staged CONFIG.
5. VERIFY: after human commit, confirm for {CLIENT}: rows show LIVE/BQ badges,
   pacing and profit-at-risk compute (no #DIV/0!-style blanks where data
   exists), the correct margin type per channel, and Executive's card for
   {CLIENT} reads from real data (note if its KPI field path is one of the
   #VERIFY-flagged ones from the inventory — check it against the client's
   dashboard and report).

COMPLETION REPORT — write PHASE3_{CLIENT}_REPORT.md: match rate and any
unmatched campaigns, extraction accuracy (fields found / flagged / wrong),
plan-format quirks the reader struggled with, verification results, and any
lesson the NEXT client run should know.
```

### CHECKPOINT 3 — per client, after each run:
- [ ] You approved every name match yourself; unmatched campaigns are explained (e.g., not yet live, DOOH with no platform account).
- [ ] You reviewed the staged extraction and committed it; anything the reader got wrong is in the report.
- [ ] Pulse shows the client with live pacing; spot-check one campaign's spend against the platform/BQ directly.
- [ ] Executive's card for the client matches its dashboard headline number.
- [ ] The report's "lessons" section is non-empty or explicitly "none."

**Exit condition for Phase 3:** every active client with a platform presence is validated, or explicitly logged as "cannot onboard because X." Track progress client-by-client — do not move to Phase 4 while a money-material client is still on sheet values.

---

# PHASE 4 — Freshness automation + cleanup

**Goal:** the Grid stays true without anyone running scripts by hand. Dead weight (SQI, retired files, misleading README claims) removed.

**Why last:** freshness only matters once the thing being kept fresh is the single, validated truth.

### Paste this prompt into a fresh Claude Code session:

```
You are executing PHASE 4 of the Grid build playbook: freshness + cleanup.

READ FIRST: grid-core/GRID_INVENTORY.md and all PHASE*_REPORT.md files.

PRECONDITION (verify, stop if false): single spine (Phase 1), merged Central
(Phase 2), and at least the money-material clients BQ-validated (Phase 3 logs
exist).

DELIVERABLES:
1. CENTRAL AUTOSYNC ON: set a sensible default sync interval (propose one and
   justify it against BQ cost/quota — we are on GCP; note if a Cloud Scheduler
   / cron-on-server split makes more sense than the in-process
   CENTRAL_AUTOSYNC_MIN mechanism, but implement the simplest reliable option
   now and document the future-proof option for the Bidbrain migration).
2. EXECUTIVE SCHEDULED: build_exec_kpis.py runs on a schedule independent of
   anyone's laptop (server cron or GCP-native — same simplest-reliable rule).
   Resolve the #VERIFY-flagged KPI field paths from the inventory: check each
   against the client's dashboard and fix or confirm, listing each in the
   report.
3. STALENESS IS VISIBLE: every tab shows when its data was last synced;
   if a source hasn't synced within 2x its expected interval, show a clear
   stale warning. No silent staleness anywhere.
4. CLEANUP:
   - Delete the static Site Quality Index from Brain (the optimization log
     STAYS — do not touch it).
   - Delete retired files: build_grid_data.py, quarantined derive.js, any
     leftover const DATA fragments, the retired Dashboards tab remnants.
   - Fix the README: the orchestrator is dormant and meta/dv360/linkedin/
     reddit connectors DO NOT exist as files — the README must say what is
     true. Do not build connectors.
   - Sweep the TODO/#VERIFY/FIXME list from inventory section 8: fix the
     trivial ones, and produce a KNOWN_DEBT.md for the rest with file+line
     and a one-line description each.

OUT OF SCOPE: Brain engine, connectors, any new features.

COMPLETION REPORT — PHASE4_REPORT.md: schedules chosen and why, #VERIFY
resolutions, everything deleted, KNOWN_DEBT.md summary, and a final statement
of what a maintainer must know to keep the Grid healthy.
```

### CHECKPOINT 4 (final):
- [ ] Leave the Grid untouched for 24 hours. Data is still current; last-synced stamps advance on their own.
- [ ] Temporarily break a sync (or simulate) — the stale warning appears. Un-break it.
- [ ] SQI is gone; optimization log intact.
- [ ] README no longer claims connectors that don't exist; `KNOWN_DEBT.md` exists and is honest.
- [ ] Show Calvin/Ben. Their numbers, live, one screen, matching the dashboards.

---

## After Phase 4 — the Grid v1 is DONE. Then, separately:

- **Brain engine** — its own project with its own diagnosis: real recommendations from BQ + the V3/V3.5 history, replacing `brain-mock-data.js`, real ClickUp round-trip. Do not start it inside this playbook.
- **Media-plan reader relaxation** — after weeks of observed accuracy: dates/budget/channel may move to auto-write; **margin, KPI, objective stay human-approved permanently.**
- **Bidbrain migration** — a connection job now, because the spine is single, BQ-native-facing, and documented: map Grid clients onto Bidbrain's Account→Client→Brand, swap SQLite for the production operational store, feed the metrics catalogue.

## Ground rules for YOU (the human), for the whole run

1. One phase per session. Fresh session each time. Paste prompts verbatim.
2. Never skip a checkpoint because "it looks fine." Checkpoints are where trust is built — the same trust you're selling to Calvin and Ben.
3. When a session reports something unanticipated, bring it to planning before acting. No solo improvisation inside a phase.
4. Keep every PHASE*_REPORT.md forever. They are the audit trail — and the story you tell when this goes into Bidbrain.