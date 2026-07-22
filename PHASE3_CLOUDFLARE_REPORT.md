# PHASE 3 REPORT — Cloudflare onboarding (reconcile + media-plan CONFIG seeding)

**Date:** 2026-07-22 · **Scope:** grid-core, Cloudflare only · **Playbook:** `grid-core/GRID_BUILD_PLAYBOOK.md` Phase 3

**Status: RECONCILE PREP COMPLETE — STOPPED at the human-approval gate (step 2 of the phase
prompt).** Match candidates are staged in the Map client panel; nothing is approved, committed
or synced. Plan ingestion (steps 3-4) and post-commit verification (step 5) are PENDING and
their sections below say exactly what is still to come.

**Session note:** this run resumed after a Claude Code process crash mid-investigation. Recovery
audit confirmed the crashed session had written NOTHING (git tree byte-identical, config
untouched, DB unsynced) — only read-only BQ pulls survived (reused). A reported pre-crash log
line ("BigQuery export: accepted_count 5") could not be corroborated against any artifact and
does not correspond to anything in this workflow (nothing in Phase 3 writes to BigQuery; the
approve route returns `{added, validated}`, not `accepted_count`). Treated as foreign
(another process/window) and staging was performed fresh from verified state.

---

## 1. Reconcile prep — what is staged and why

### The staged surface (new, reusable for every next client)

Generic fuzzy matching is structurally useless for Cloudflare: BQ names are ~60-char taxonomy
strings (`CLOUD_ACQ_2026-Q2_CNC_TTD_..._ANZ-CORE-DG`), Grid rows are short program names
("Q2 Core DG"), so dice scores are noise — the old endpoint force-preselected the single best
match even at 5%. Honoring "do not force-match" needed two things:

1. **`grid-core/config/reconcile-staged/Cloudflare.json`** — a curated, evidence-based candidate
   list: 14 pairs, each with the match rule (`mode`+`value`), confidence (12 high / 2 medium),
   rationale, and a BQ preview (names matched + spend). Served by `GET /api/central/reconcile/:client`
   as `staged`; rendered FIRST in the Map client panel, **unticked** — the human ticks and
   approves through the unchanged `/approve` route. "Select all high-confidence" is a selection
   helper, not an auto-approve. The file writes nothing by existing.
2. **Honest flags on the generic fuzzy list** (`server.js`): suggestions now carry
   `flag: 'weak'` (best dice < 0.35 or only cross-channel candidates — nothing preselected,
   "no match" chip) or `'ambiguous'` (runner-up within 0.06 — runner-up shown). Channel-aware
   ranking: a cross-channel row can never outrank an in-channel one, so platforms cannot
   silently cross-match. On Cloudflare's 72 BQ names: 70 weak / 1 ambiguous / 1 clean —
   which is the honest picture, and why the staged list exists.

### Match rate

Grid has **16 Cloudflare rows**. Staged coverage:

| Outcome | Rows | Detail |
|---|---|---|
| Staged high-confidence | 12 | 6 LinkedIn (ANZ-DNB, CF1 India, Coles Hyper, Fonterra Hyper, PEYC, Q3 Core DG) + 6 TTD (Coles DOOH AU, Coles DOOH NZ, Coles Prog, Q2 Core DG, Q3 Core DG, Surround ABM) |
| Staged medium (flagged, human decides) | 2 | Q2 Core DG · LinkedIn (PUBSEC gap, below), Q2 Core DG · Reddit (two-brief ambiguity, below) |
| Unmatchable — no BQ platform data (said plainly, NOT cross-matched) | 2 | Q2 Core DG · **LINE** (no LINE table in the raw layer — manual seed only), Q3 Core DG · **Google Ads** (no Cloudflare account in `google_ads_apac` — accounts are STT-only; row is Paused, no spend) |
| BQ-only orphan (no Grid row) | 1 | LinkedIn **VER-PUBSEC** group, $1,225 (see below) |

**Every one of the 103 campaign-level BQ names is accounted for**: the 6 TTD rules cover all
49 TTD names with zero overlap and zero leftovers; the 21 LinkedIn groups partition into the
7 staged rules + PUBSEC; both Reddit names fall under the one flagged rule.

### The two decisive discoveries (next clients inherit both)

1. **LinkedIn program membership lives in `CAMPAIGN_GROUP_NAME`, not campaign names.** No
   campaign-name token separates PEYC's 6 campaigns from ANZ Core DG's 5. Cloudflare's spec in
   `central-clients.json` now sets the LinkedIn `campaignColumn` to the GROUP column — after
   which group totals reconcile with the sheet almost to the dollar: PEYC $26,105 vs sheet
   $26,099 · CF1 $6,227 vs $6,225 · Coles Hyper $13,051 vs $13,050 · Fonterra $13,054 vs
   $13,050. That agreement is the evidence behind the "high" confidences.
2. **TTD names exist in two vintages** (mid-flight rename adds a numeric job prefix: `2103_`,
   `2193_`, `2479_`) — `contains` rules on the stable suffix token span both vintages and sum
   correctly. Exact-name matches would silently drop the renamed half.

Also fixed while staging: Cloudflare TTD **impressions** live mostly in the legacy `IMPRESSION`
column (verified per campaign group) — the spec's `impressionColumn` is now
`COALESCE(IMPRESSIONS, IMPRESSION)`, the same per-row rule Schneider's validated staging view uses.

### Flagged items awaiting the human's judgment (not forced)

- **Q2 Core DG · LinkedIn (medium):** staged rule `contains CORE-DG` = 6 groups, $44,304. The
  sheet's figure is $45,522 — gap $1,218 ≈ the VER-PUBSEC group ($1,225, within $7). The sheet
  apparently folded PUBSEC into Q2 Core DG; one contains-rule cannot span both token sets.
  Recommended: approve as staged and add a separate PubSec row for the orphan (or accept the
  documented $1.2k gap). Cannot stack two map rules on one row — `syncCampaignMetrics`
  overwrites, it does not add.
- **Q2 Core DG · Reddit (medium):** Reddit holds exactly 2 campaigns from two different briefs —
  CNC retargeting ($1,811) + MDS "SHADOW-AI" awareness ($8,451). Sum $10,262 vs sheet $9,891
  (~4% over), so the sheet row appears to span both; the staged rule catches both. Approve only
  if SHADOW-AI genuinely belongs to Q2 Core DG; otherwise switch to an exact rule on the CNC name.
- **Coles Prog · TTD (staged high, worth an eyeball):** the BQ name says "HyperlocalGeo", not
  Coles — but spend equals the row's budget to the dollar ($9,900), the May 4-31 flight matches
  exactly, and it is the only TTD name not claimed by another rule.

### ⚠ THE MONEY FINDING — TTD `COSTS` is the CLIENT-BILLED basis (affects Schneider too)

Verified two independent ways:
- Cloudflare Q2 Core DG TTD (ended, so totals are final): `SUM(COSTS)` = **$87,583** vs sheet
  clientSpend **$85,252** / budget **$86,826** — vs the sheet's media-cost figure $24,257.
- Schneider Airset TTD date-bounded to the old sheet vintage (2026-07-08): `SUM(COSTS)` =
  **$2,798** ≈ the old billed figure $2,650, not the media-cost figure $995.

Consequence: the sync convention writes BQ spend → `mediaSpend`, then
`clientSpend = mediaSpend × spendMult`. Cloudflare's three in-flight TTD rows carry
`spendMult` 3.07-3.59 (derived from the sheet's media-cost basis). On a billed-basis feed the
first sync would set clientSpend ≈ **3.5× the true billed spend** (Q2 Core DG: ~$308k on an
$86.8k budget → 354% "spent", garbage pacing and profit-at-risk).
**Before the first Cloudflare sync, the human must set `spendMult = 1` on the 3 TTD rows**
(Q2 Core DG, Q3 Core DG, Surround ABM). Spend Mult is now a first-class Central column (Margin
group, always inline-editable) added on request after this finding — edit it right in the table. With mult=1,
clientSpend = billed COSTS (true), pacing is correct, and profit-at-risk stays correct because
TTD uses **Platform Margin** under the Phase 1 rule (0.65 / 0.6 / 0.6 are set on these rows) —
the realized campaignMargin display will read ~0%, which is a known cosmetic consequence, not
a money error. **Carry-forward: Schneider's already-validated map has the same landmine**
(its `pm_delivery` spend is the same COSTS basis; its TTD rows carry spendMult ≈ 2.66) — no
real sync has ever run in this DB (`lastSyncedAt` null everywhere), so nothing is corrupted yet,
but planning must resolve Schneider's TTD spendMults before its first sync. calc.js untouched
(frozen) — this is a data-basis issue, not a formula issue.

### Standing-rule compliance check

- **Reader auto-write path:** verified NONE exists — `plan-reader.js` produces a draft only;
  the commit route writes only user-confirmed values, whitelisted to CONFIG
  (`CENTRAL_PLAN_FIELDS`), rejects derived fields and unacknowledged overwrites. Nothing to
  disable.
- **Reconcile writes:** only `POST /approve` writes (to `central-clients.json`), human-triggered.
  Staged file + endpoint changes are read-only surfaces.
- **Margin rule:** untouched (calc.js frozen, byte-identical). Extracted-margin field routing
  will be exercised in the plan-ingestion step.
- One trust-model nuance to know: the reconcile-staged file is trusted config — path-traversal
  is guarded (`path.basename`), but the file's campaignIds are not re-validated against the DB
  until approve resolves them (`resolveCampaignId` falls back by name, unresolvable → skipped).

## 1b. Platform-consistency review (2026-07-22 — human rejected the first staging pass)

The human declined to approve, reporting cross-platform matches (LINKEDIN names offered against
LINE/TradeDesk rows, etc.). Audit findings, with evidence:

- **The report was correct for the pre-Phase-3 matcher**: replaying the old algorithm (pure dice
  over all 16 rows, best always preselected) against the same 72 BQ names preselects
  **18/72 cross-platform** — e.g. every `..._CNC_LINKEDIN_..._CORE-DG` group preselected onto
  **Q2 Core DG · TradeDesk**. Root cause exactly as described: four same-named "Q2/Q3 Core DG"
  rows across TradeDesk/LinkedIn/Reddit/LINE, and no channel dimension in the scorer.
- **The 14 staged pairs were already platform-clean** (14/14 pass the token rule: every BQ name
  each rule matches carries the token of its pair's platform, and each pair's channel tag equals
  its Grid row's channel). The confirmed-good rows the human listed (Surround ABM, both DOOH,
  Fonterra/Coles Hyper, CF1, ANZ-DNB) are staged unchanged.
- **The requested hard rule is now enforced in code** (was previously only a channel-aware sort +
  weak flag): `platformFromName()` reads the token in the BQ name — LINKEDIN → Linkedin;
  TTD / TRADE DESK → TradeDesk; REDDIT → Reddit; LINE **as a standalone token** (regex-guarded so
  it can never fire inside LINKEDIN) → LINE; DV360 → DV360. A candidate must satisfy BOTH the
  name token (when present) and the source-table channel tag (when present); names with no token
  (the DOOH ones) are constrained by the table tag alone. No compatible row →
  `flag: 'no-platform-match'`, nothing preselected.
- **The approve route is also guarded**: a pair whose value token or channel tag conflicts with
  the Grid row's channel is rejected with 400 and nothing written. Verified live: posting the
  PEYC LinkedIn group against the LINE row returned
  `"platform mismatch: ... cannot map to 'Q2 Core DG' on channel 'LINE' — nothing was written"`,
  and the config was confirmed unchanged after.
- **Rebuilt candidate list (post-gate), verified against a live server**: 72 suggestions,
  **0 platform crossings anywhere** (including runner-ups); flags 70 weak / 1 ambiguous / 1 clean /
  0 no-platform-match (every Cloudflare BQ name has at least one same-platform Grid row).
- **Unmatched after the platform filter** (unchanged from §1, now machine-enforced):
  `Q2 Core DG · LINE` and `Q3 Core DG · Google Ads` are never offered a candidate — no BQ data
  exists on those platforms (LINE has no raw table; `google_ads_apac` has no Cloudflare account).
  Additionally, generic fuzzy alone would leave **Coles Prog · TradeDesk** and **PEYC · Linkedin**
  unmatched (zero name similarity) — they are matched only by the staged evidence-based pairs
  (spend = budget to the dollar / group-total agreement).

Staged file re-staged with a `platformAudit` record; approval remains entirely with the human.

**Follow-up (same day): "the fix didn't take effect" — root cause was a STALE SERVER PROCESS,
not the code.** The reviewer's grid was served by a `node server.js` started at 11:28 AM —
hours before any Phase 3 edit — and their Ctrl+C/restart did not replace it (a second
`node server.js` on a taken port dies with `EADDRINUSE` while the page keeps talking to the old
process, which still ran the original channel-blind matcher — reproducing all 18 crossings and
never showing the staged block). Confirmed by process start time (11:28 AM) vs fix mtime
(2:41 PM), and by the old instance serving the NEW files statically (disk) while running OLD
route code (memory). Resolution: stale process killed; fresh instance verified against a real
BQ pull — 0 crossings across all 72 suggestions + runner-ups, 0 LinkedIn-name suggestions onto
TradeDesk/LINE rows, crossed approve rejected 400 with config untouched. A TEMP token log inside
`platformFromName()` prints every BQ name + extracted token on "Load BQ names" (marked TEMP in
server.js — remove after the review sign-off). Lesson for every future run: after editing
server code, verify the RUNNING process vintage (start time vs file mtime), not just the file —
and treat "restart" claims as unverified until the old PID is confirmed dead.

## 2. Name inline-fillable (scope addition, reported separately)

Phase 2 finding #3 resolved: an empty campaign name now renders the standard fill-empty
affordance inside Central's Campaign cell (placeholder "add name", amber needs-input tint on
the cell, counted by the missing-fields badge — `name` added to `NEEDS_INPUT`). Typing a name
saves through the existing whitelisted field route. The affordance appears **only when the name
is empty** — named rows are not editable in place.

Honesty note on "UI-layer only": one line beyond the UI was required — `name` added to
`CENTRAL_EDIT_FIELDS` in `src/brain/db.js`, because the server whitelist rejected `name` on the
edit scope (it was already writable via the plan scope, so this is the same governance class,
human-typed CONFIG). Side effect to be aware of: the API route technically accepts a rename of
a named row (same trust level as every other CONFIG edit); the UI still only offers fill-empty.
The known beneficiary is `Ad Assembly · (no name) · TradeDesk`.

## 3. Files changed this run

- `grid-core/config/central-clients.json` — Cloudflare spec: LinkedIn `campaignColumn` →
  `CAMPAIGN_GROUP_NAME`; TTD `impressionColumn` → `COALESCE(IMPRESSIONS, IMPRESSION)`; notes
  incl. the billed-basis warning. `validated` stays **false**, `map` stays **empty**.
- `grid-core/config/reconcile-staged/Cloudflare.json` — NEW: the staged candidate list (pilot
  of the staged-reconcile pattern).
- `grid-core/server.js` — reconcile GET: serves `staged`; **hard platform-consistency gate**
  (`platformFromName` name-token rule + table channel tag, both enforced;
  `flag: 'no-platform-match'` when no same-platform row exists), weak/ambiguous flags
  (`RECONCILE_WEAK_BELOW = 0.35`); `/approve` rejects platform-crossing pairs (400, nothing
  written).
- `grid-core/src/central/plan-panel.js` — Map client panel: staged block (confidence chips,
  rationale tooltips, previews, warnings, unmatchable/orphan notes, select-high helper),
  staged rows collected into the same approve payload; weak generic rows no longer preselect.
- `grid-core/src/brain/db.js` — `CENTRAL_EDIT_FIELDS` + `name` (one line, see §2).
- `grid-core/src/central/render-central.js` — `NEEDS_INPUT` + `name`; Campaign-cell fill-empty
  affordance; needs-tint keys on `name` for the campaign column.
- `grid-core/README.md` — staged-reconcile + name-fillable notes in the reconcile section.
- `PHASE3_CLOUDFLARE_REPORT.md` — this file.
- **Not changed:** `calc.js` (frozen — verified untouched), the sync path, the approve route,
  Schneider's config, any client dashboard.

Verification run: all 6 test suites pass (128 assertions, 0 failures); syntax-checked the three
edited JS files; live re-pull of `--names Cloudflare` confirms group-grain LinkedIn (21 groups;
PEYC 1 / CORE-DG 6 / COREDG-Q3 8 — matching the staged previews); endpoint verified against a
live server (staged block present: 14 pairs, 3 warnings, 2 unmatchable, 1 orphan; generic flags
70 weak / 1 ambiguous / 1 none; test server stopped afterwards).

## 4. PENDING — plan ingestion (steps 3-4 of the phase prompt)

**Waiting on the human for Cloudflare's media plan file(s)** — not in the repo (the
committed `targets/real_targets.csv` in `clients/client_cloudflare/` is the dashboard seed, not
the agency media plan the reader ingests). When provided, each file goes through the reader
(stage-only), producing per-field source location + confidence; missing fields get flagged, not
guessed; objectives/KPIs map onto the existing vocabulary or get flagged. Extraction accuracy
(found / flagged / wrong after human review) and plan-format quirks will be reported here.

## 5. PENDING — post-commit verification (step 5)

After the human approves matches (+ resolves the TTD spendMult warning) and commits the plan
extraction, this section gets: LIVE/BQ marker counts, pacing + profit-at-risk numbers against
synced spend, per-channel margin-type check (TTD rows must use Platform Margin), and the
Executive card check — Cloudflare's KPI object is one of the 7 `#VERIFY` stubs
(`config/kpi-objects/cloudflare.json`, `"stub": true`), so its card's KPI field path must be
checked against the Cloudflare dashboard headline and the result reported.
**Sync note for the human:** most Cloudflare rows are Ended — the first backfill needs
`POST /api/central/sync?includeEnded=1` (the Sync now button does not pass it).

## 6. Carry-forward for the SCHNEIDER Phase 3 run (recorded, not acted on)

1. **The three `Software First EcoStruxure · Linkedin` rows are NOT duplicates.** The source
   sheet distinguishes them by **Objective** (Awareness / Retargeting 1 / Consideration; a 4th
   row is TradeDesk Awareness). The import failed to carry the Objective distinction for two of
   them — Phase 2's "likely duplicate" read was wrong. Schneider's Phase 3 run must fix those
   objectives BEFORE its re-reconcile (do not archive either row as a "duplicate").
2. **TTD billed-basis spendMult landmine** (§1) — resolve Schneider's TTD spendMults before its
   first real sync.
3. **YES — Schneider's validated map has its own (worse) version of the platform-crossing
   problem.** Asked directly after the Cloudflare review; verified against the DB + BQ:
   - Schneider is **Mode A**: `pm_delivery` aggregates each program **across platforms** and the
     map sends each program's total to ONE Central row. The fuzzy matcher isn't involved, but the
     platform dimension is still lost — 4 of the 5 mapped names have TWO channel-rows
     (Water and Environment, Airset, NEL: TradeDesk + Linkedin; Advancing Energy T: Linkedin +
     Google Ads; only EBA is single-row).
   - **All 5 mapped `campaignId`s are STALE** (the DB was rebuilt since the map was written —
     none resolve). Sync falls back to (client, name), which picks the FIRST same-named row:
     TradeDesk for W&E/Airset/NEL/EBA, Linkedin for Advancing Energy T. So the blend lands on an
     arbitrary channel row, silently.
   - Blend sizes (pm_delivery, whole-history AUD): **nel = $2,145 TTD + $8,209 LinkedIn (79%
     foreign spend onto a TradeDesk row)** · water_env = $2,536 TTD + $2,952 LinkedIn (54%
     foreign) · airset = $4,721 TTD + $2,376 LinkedIn (33% foreign) · global_rebrand = LinkedIn-
     only $2,741 (correct row by luck) · eba = TTD-only $12,017 (safe, 1:1 as the config noted).
   - Consequence if synced as-is: blended spend on a TTD row gets the **Platform-Margin**
     treatment (and the TTD spendMult re-multiplication from carry-forward #2) for LinkedIn
     dollars that should use Campaign Margin — compounding both landmines. **Ent IT** (the
     example raised): both rows exist, but Ent IT is NOT one of pm_delivery's 6 programs and is
     not in the map — it never syncs, so it is unaffected today.
   - No damage has occurred: no real sync has ever run (`lastSyncedAt` null on all rows).
     **Schneider's Phase 3 run must split the map per platform** (add `platform` to the
     pm_delivery fetch, or move Schneider to Mode B per-channel rules like Cloudflare) before its
     first sync. Not fixed in this run — Cloudflare-only scope.

## 7. Lessons the next client run inherits

1. **Check the grain before matching names.** The platform's grouping column (LinkedIn campaign
   groups here) may be the only place program membership exists. If sheet-vs-BQ totals agree at
   some grain, that grain is the mapping unit — switch the spec's `campaignColumn` rather than
   fighting 50 campaign names with fuzzy scores.
2. **Budget/spend agreement is the real confidence signal**, not name similarity. Three matches
   here were provable to the dollar with zero name overlap (Coles Prog ← "HyperlocalGeo").
3. **Expect mid-flight renames on TTD** (numeric job prefix). Prefer `contains` on the stable
   token; verify the token set partitions cleanly (each BQ name claimed by exactly one rule).
4. **Verify the cost-basis of every raw feed before trusting spendMult.** Date-bound the BQ sum
   to the sheet vintage and compare against BOTH sheet columns (media vs billed). Two clients in,
   `raw_snowflake` TTD `COSTS` = billed; LinkedIn/Reddit `COSTS` = billed = media (mult 1).
5. **Check both impressions columns** (`IMPRESSIONS` vs legacy `IMPRESSION`) on
   `tradedesk_apac_all` — coverage varies per campaign, COALESCE per row.
6. **Write the staged file, not ad-hoc notes** — `config/reconcile-staged/<Client>.json` is now
   a first-class surface the panel renders; the next session only has to fill it.
7. **Ended rows need `?includeEnded=1`** for their one-time backfill sync.
8. **Platform consistency is a hard rule, at two layers.** Same-named rows across channels
   (Q2 Core DG ×4 here) make channel-blind matching structurally wrong — the matcher now
   hard-filters by the BQ name's platform token + the source-table tag, and `/approve` rejects
   crossings outright. When staging a Mode A (view) client, remember the view itself can erase
   the platform dimension (Schneider §6.3) — check the map grain, not just the matcher.
9. **Verify map `campaignId`s still resolve** — a DB rebuild silently invalidates them and the
   (client, name) fallback picks the FIRST same-named row regardless of channel (§6.3). A
   re-reconcile after any rebuild is cheap insurance.
