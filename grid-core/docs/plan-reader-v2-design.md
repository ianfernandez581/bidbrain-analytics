# Plan-reader v2 — design (spec + module skeleton. DESIGN ONLY — nothing wired into server.js)

**Status: NOT BUILT.** This document is the design the eventual build implements. The v1 reader
(`src/central/plan-reader.js` + `plan-panel.js`, routes `/api/central/plan/*`) stays untouched
and in service until v2 replaces it.

**The strategic driver, in the product owner's words:** future clients "might not have their
central sheet... I just don't want the Grid to be dependent on a central sheet." Cloudflare's
plans happened to agree with Central because a human buyer had already curated Central — a happy
accident of the old workflow, not a property of the Grid (PHASE3_CLOUDFLARE §10.4). **The reader
is the primary seeding path for any client without a central sheet**, so it must stand on its
own: know the basis of every number it extracts, work identically whether or not a Grid row
already exists, and never write anything a human did not explicitly approve.

---

## Requirements

### R1 — Basis detection (the founding requirement)

Every extracted **budget** (and budget-like money field) carries
`basis ∈ {media, billed, unknown}`.

- Plans state the MEDIA budget; Grid budgets are CLIENT-BILLED — ~2× apart on fee-loaded rows
  (§10.2: 1.2×–2.7× across Cloudflare's plans). Writing a plan budget into `totalBudget` without
  basis normalization halves the budget and mis-fires pacing + profit-at-risk on every
  fee-loaded row — the same failure class as the §1 spendMult landmine.
- **Detect from the plan itself where possible.** The known positive signal: a fees breakdown on
  the plan (the Q2 Core DG plan carries `Planning 7% + Reporting 6% + Tech 4%` at rows 20–22) ⇒
  the headline figure is **media**, and `billed = media × (1 + Σ fees)` can be offered as a
  computed SUGGESTION (never auto-written). A plan whose total reconciles against a stated
  client-invoice/billed line ⇒ **billed**. Anything else ⇒ **unknown**.
- **`unknown` REQUIRES the human to choose at commit time** — the commit route rejects a budget
  write whose staged basis is `unknown` unless the approval payload carries an explicit
  `basisChoice`. No default, no guess.
- Downstream writes record the decision into the row's **`spendBasis`** (the same field the sync
  writes), so calc/consumers always know which figure they are looking at.

### R2 — One flow, two starting states

Staging is IDENTICAL whether or not a Grid row exists; the difference is only what the diff
shows on screen:

- **Row exists:** per-field diff — plan value (with provenance) vs current Grid value (with its
  provenance from `central_rows`). The human picks the winner PER FIELD (default = KEEP the Grid
  value, matching v1's conflict default).
- **No row:** the same diff with an **empty right side**; approving creates the row
  (`sourceOfRecord: 'plan'`, `status: 'Draft'` unless the plan states otherwise).
- **No separate code paths** — one `stage → diff → commit` pipeline; "create" is just a commit
  whose target is `'create'` instead of a `campaignId`.

### R3 — CONFIG columns only; provenance; no auto-commit, ever

- Extractable fields = the CONFIG set only: budget (`budgetGross`/`totalBudget`), KPI
  (`keyKpi`/`kpiTarget`), `objective`, flight dates (`startDate`/`endDate`), margin
  (`platformMargin`), `channel` — plus the v1 identity/plan fields (`client`, `name`,
  `jobNumber`, `managedBy`, `forecastCpm`, `adServingCost`, `spendMult`, `notes`). **Never
  actuals** (`impressions`/`mediaSpend`/`clientSpend` are the sync's, DERIVED fields are
  nobody's) — enforced server-side by the existing `CENTRAL_PLAN_FIELDS` whitelist +
  `CENTRAL_DERIVED_FIELDS` rejection in `src/brain/db.js`, which v2 reuses verbatim.
- **Per-field provenance:** `{file, sheet, cellRef|page}` + `confidence` on every extracted
  value (v1's shape, plus the source file). A value with no provable source cell does not get
  invented — it gets flagged missing.
- **No auto-commit path exists.** v1's posture ("it NEVER writes a campaign row") is permanent
  in v2. The playbook's "post-launch relaxation" idea may someday auto-write dates/budget/
  channel, but **margin, KPI and objective stay human-approved permanently** — and none of that
  relaxation is in this design.

### R4 — Controlled vocabulary + KPI suggestions (flag, don't invent)

- Objectives/KPIs map onto Central's existing controlled vocabulary (the values already in the
  DB: Awareness/Reach, Site Traffic / LGF, Lead Generation, Page Lands, ROAS, …). Plan wording
  that maps cleanly is mapped with the mapping recorded; wording that doesn't is **flagged, not
  invented** — no new categories from the reader. (Cloudflare lesson: plan wording "Awareness" /
  "Lead Gen" is LESS specific than Central's values — a silent map would downgrade specificity.)
- **KPI derivation heuristics are SUGGESTIONS, always flagged.** The owner's ask: the KPI should
  follow from objective + plan + funnel stage (e.g. awareness/TOFU + display ⇒ CPM/reach KPI;
  consideration ⇒ CTR/CPC; lead-gen/BOFU ⇒ leads/CPL). The engine may propose
  `keyKpi`/`kpiTarget` from those rules when the plan states none — rendered with a distinct
  "suggested — confirm" treatment and committed only by explicit human approval, like any other
  field.

### R5 — Format resilience (adapters + generic fallback)

The five Cloudflare plans are the reference corpus for real-world variety: Activation-Plan
grids; Cover-sheet + Platform-Allocation workbooks; several per-client sheets in one file;
V1/V2 sheet pairs in one workbook; literal-string dates ("May 12th"). Design:

- An **extraction layer of per-format-family adapters**, each owning `sniff()` (how confident am
  I this workbook is my family?) and `extract()`. Highest sniff score wins; ties/low scores fall
  through.
- A **generic fallback** adapter (evolved from v1's header-keyword heuristic + LLM path) that
  extracts what it can, tags everything `confidence:'low'`, and flags the rest — a plan the
  adapters don't recognize must degrade to a mostly-empty review panel, **never a dead end and
  never a guess**.
- Cross-cutting normalizers shared by all adapters: date coercion (incl. literal strings via
  `parser.js`'s `_parseDate`), money/percent coercion, **sheet-version resolution** (a V1/V2
  pair ⇒ extract the highest version, warn that an older version exists), **multi-client
  fan-out** (per-client sheets in one file ⇒ one staged extraction per client, each row carrying
  its client).

---

## Skeleton

### File layout

`src/plan-reader-v2/` (repo convention is `src/`, not `lib/`; same layout otherwise):

```
src/plan-reader-v2/
  index.js            ← public API: stagePlan / diffStaged / commitStaged / discardStaged
  detect-basis.js     ← R1: basis detection + fee-schedule math (pure functions)
  vocab-map.js        ← R4: controlled vocabulary + KPI-suggestion heuristics (pure)
  stage.js            ← staged-extraction persistence (config/plan-staged/*.json) + diff builder
  adapters/
    _adapter-base.js  ← the adapter contract + shared normalizers (dates, money, versions)
    activation-grid.js
    cover-allocation.js
    per-client-sheets.js
    versioned-pairs.js
    generic-fallback.js  ← always matches, lowest priority; everything confidence:'low'
```

Staged extractions persist as files in **`config/plan-staged/<stagedId>.json`** — deliberately
mirroring the `config/reconcile-staged/` pattern: a staged file is a PROPOSAL that writes
nothing by existing, survives server restarts (v1 drafts don't), and is reviewable in git/by eye.

### Staged-extraction JSON schema

```jsonc
{
  "stagedId": "plan-2026-07-23-a1b2c3",
  "client": "Acme",                    // per-client fan-out ⇒ one staged file per client
  "sourceFile": "Acme_Q3_Media_Plan_v2.xlsx",
  "adapter": "cover-allocation",       // which family matched (or "generic-fallback")
  "preparedAt": "2026-07-23T04:00:00Z",
  "preparedBy": "plan-reader-v2",
  "basis": {                           // R1 — plan-level detection
    "value": "media",                  // media | billed | unknown
    "evidence": "fees breakdown found: Planning 7% + Reporting 6% + Tech 4% (Sheet 'Plan' rows 20-22)",
    "feePct": 0.17,                    // present only when a fee schedule was found
    "billedFactor": 1.17               // suggestion only — commit still requires the human
  },
  "warnings": [                        // rendered at the top of the review panel, like reconcile-staged
    "sheet 'Media Plan V1' ignored in favour of 'Media Plan V2'",
    "no margin stated anywhere in the plan"
  ],
  "rows": [                            // one entry per campaign line found in the plan
    {
      "matchCandidate": {              // null when no Grid row plausibly matches (⇒ create flow)
        "campaignId": "cmp-1234abcd",
        "campaignName": "Q3 Brand Push",
        "channel": "TradeDesk",
        "how": "name+channel+flight overlap"
      },
      "fields": {
        "totalBudget": {
          "value": 42190,
          "basis": "media",            // budget-like fields carry their own basis (R1)
          "provenance": { "file": "Acme_Q3_Media_Plan_v2.xlsx", "sheet": "Plan", "cellRef": "F14" },
          "confidence": "high"         // high | medium | low
        },
        "startDate": {
          "value": "2026-08-01",
          "provenance": { "file": "…", "sheet": "Plan", "cellRef": "C4" },
          "confidence": "medium",
          "note": "parsed from literal 'Aug 1st'"
        },
        "objective": {
          "value": "Awareness/Reach",
          "raw": "Awareness",          // the plan's wording, kept for the audit trail
          "provenance": { "file": "…", "sheet": "Plan", "cellRef": "B2" },
          "confidence": "high",
          "vocabFlag": null            // or "unmapped: '<raw wording>'" — flagged, not invented (R4)
        },
        "keyKpi": {
          "value": "CPM",
          "suggested": true,           // R4 — funnel heuristic, distinct UI treatment, human must confirm
          "rationale": "awareness objective + display channel ⇒ CPM (funnel heuristic)",
          "confidence": "low"
        }
      },
      "missing": ["platformMargin", "kpiTarget"]   // flagged, never guessed
    }
  ]
}
```

### API surface (new routes; v1's `/api/central/plan/*` untouched until cut-over)

```
POST /api/central/plan2/stage
  body: { filename, contentBase64, client? }
  → runs adapters → writes config/plan-staged/<id>.json → { stagedId, staged }
  Writes NOTHING to campaigns.

GET  /api/central/plan2/:id/diff
  → { rows: [ { matchCandidate|null, fields: {
        <field>: { plan: {value,basis?,provenance,confidence,...},
                   grid: {value, provenance}|null } } } ] }
  One shape for both starting states — grid side is null when no row exists (R2).

POST /api/central/plan2/:id/commit
  body: {
    approvedBy: "name",                       // required, like the definitions editor
    rows: [ {
      target: "cmp-1234abcd" | "create",      // create ⇒ new row, sourceOfRecord:'plan'
      fields: { "totalBudget": { take: "plan" },   // explicit PER-FIELD approval —
                "startDate":   { take: "grid" },   // absent field = untouched, always
                "keyKpi":      { take: "plan", value: "CPM" } },
      basisChoice: "media" | "billed" | null  // REQUIRED when a taken budget's basis is
    } ]                                       // 'unknown' (R1); recorded into spendBasis
  }
  → validates against CENTRAL_PLAN_FIELDS / rejects DERIVED (existing db.js governance),
    rejects unknown-basis budget writes without basisChoice, writes via
    db.updateCampaignField / db.createCampaign (provenance into central_rows),
    read-back-verifies every write, archives the staged file with the outcome.

POST /api/central/plan2/:id/discard
```

There is **no route that commits without a per-field approval payload** — omitting `fields`
commits nothing. This is the structural encoding of "no auto-commit path, ever" (R3).

### Function signatures (stub bodies are the build's job)

```js
// index.js
async function stagePlan({ filename, buffer, client }) {} // → StagedExtraction (writes the staged file only)
function diffStaged(staged, campaigns, overrides) {}      // → per-row, per-field {plan, grid|null}
async function commitStaged(stagedId, approvalPayload, db) {} // → {written[], created[], rejected[]}
function discardStaged(stagedId) {}

// detect-basis.js  (pure — unit-testable against the 5 Cloudflare plans as fixtures)
function detectBasis(workbookModel) {}   // → {value:'media'|'billed'|'unknown', evidence, feePct?, billedFactor?}
function findFeeSchedule(workbookModel) {} // → {fees:[{label,pct,cellRef}], total} | null
function toBilled(mediaAmount, feePct) {}  // → mediaAmount × (1+feePct) — SUGGESTION math only

// vocab-map.js  (pure)
const OBJECTIVE_VOCAB = [/* Central's live values — read from the DB at build time, not hardcoded twice */];
function mapObjective(rawWording) {}      // → {value|null, raw, vocabFlag|null} — flag, don't invent
function mapKpi(rawWording) {}            // → same contract
function suggestKpi({ objective, channel, funnelStage, planKpis }) {} // → {value, rationale, suggested:true}|null

// adapters/_adapter-base.js — the adapter contract
// each adapter exports: { name, sniff(workbookModel) → 0..1, extract(workbookModel) → ExtractedRow[] }
function toWorkbookModel(buffer, filename) {}  // SheetJS/parser.js → neutral {sheets:[{name, cells[]}]}
function resolveSheetVersions(workbookModel) {} // V1/V2 pairs → highest version + warning
function splitPerClientSheets(workbookModel) {} // → [{client, workbookModel}] fan-out
function coerceDate(raw) {}                     // handles "May 12th" etc. via parser.js _parseDate
function coerceMoney(raw) {} 
function coercePct(raw) {}

// stage.js
function writeStaged(staged) {}          // → config/plan-staged/<id>.json (path.basename-guarded)
function readStaged(stagedId) {}
function archiveStaged(stagedId, outcome) {}
```

### What v2 reuses from v1 (no duplication)

- `src/brain/parser.js` text extraction (PDF/DOCX/PPTX) + `_parseDate`; SheetJS for grids.
- The LLM-assisted extraction path (Claude when `ANTHROPIC_API_KEY` is set) lives INSIDE
  `generic-fallback.js`; deterministic heuristics remain the no-key path. An LLM output is
  subject to the same provenance/confidence/vocab rules — it proposes, adapters and humans
  dispose.
- `db.js` governance (`CENTRAL_PLAN_FIELDS`, derived rejection, provenance writes) — v2 adds the
  basis gate ON TOP of it, changes nothing inside it.
- The review-panel UI pattern from `plan-panel.js` (conflict keep/replace, low-confidence dots)
  extends to render basis chips, suggestion treatment, and the empty-right-side create flow.

### Explicitly out of scope for this design

- Wiring into `server.js` / the UI (the build does that; this document is the contract).
- Any auto-write relaxation (see R3 — margin/KPI/objective are human-approved permanently).
- Plan ingestion for actuals/pacing history (Brain V3's lane, not the reader's).
- FX handling — a plan in a currency other than the client's Grid currency is a warning + stop,
  same rule as the sync.
