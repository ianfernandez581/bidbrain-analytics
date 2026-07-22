# grid-core

The data + calculation core for **The Grid**. This is the layer that turns
"the probe reaches the platforms" into "the app shows numbers you can trust."

Two consumers import from here:
- the **live app** (dashboard) calls `orchestrator.fetchLiveCampaigns()`
- the **reconciliation harness** (`reconcile.js`) calls the same thing, so the
  dashboard and the spreadsheet can never disagree.

## What's here

```
src/
  derive.js                 ← authoritative Live-Campaigns formulas (THE source of truth)
  derive.test.js            ← proves derive reproduces the sheet's own values
  orchestrator.js           ← fan out to connectors, tag provenance, run derive
  reconcile.js              ← compare pulled numbers vs platform UI, to the cent
  connectors/
    connector-base.js       ← ProbeError, httpJson, pollUntil, normalizedRow
    google-ads.js           ← SYNC pattern (reference implementation)
    trade-desk.js           ← CREATE-POLL pattern (reference implementation)
    meta.js / linkedin.js / reddit.js / dv360.js   ← follow the same two patterns
```

Meta, LinkedIn, Reddit follow the `google-ads.js` (SYNC) shape.
DV360 follows the `trade-desk.js` (CREATE-POLL) shape.

## The formulas (transcribed from CENTRAL_100__Digital.xlsx → "Live Campaigns")

| Field | Formula | Sheet col |
|---|---|---|
| Ad-serving cost | `impressions/1000 × adServingRate` | M |
| Campaign margin | `(clientSpent − mediaSpend − adservingCost) / clientSpent` | J |
| CPM performance | `(clientSpent / impressions) × 1000` | O |
| Budget remaining | `totalBudget − clientSpent` | W |
| % budget spent | `clientSpent / totalBudget` | X |
| % flight elapsed | `MIN((today − start)/(end − start), 1)` | Y |
| Pacing status | `%spent / %elapsed` (ratio; >1 over, <1 under) | Z |

**Platform margin (K)** is a manual input, not derived — passed through.
The sheet's manual `×2` / `÷2` fudge cells are **deliberately not reproduced**;
the APIs return true full-flight numbers, so reproducing them would double-count.

Verify anytime: `npm test` (runs `derive.test.js` against real sheet rows).

## The campaign data (`const DATA` in `the-grid.html`)

The grid renders every campaign from a `const DATA = [...]` literal embedded in
`the-grid.html`. That literal is a **transcription of the committed source sheet**
`bidbrain-platform/Data/Central2.xlsx` ("Live Campaigns"), holding only the raw
sheet columns — the grid derives pacing/margin/projection at runtime (`derive()`).

**It is generated, not hand-edited.** When the sheet grows (new campaigns, new
clients, updated spend) the embedded copy goes stale and the grid shows fewer
campaigns than the sheet. Regenerate it for **all clients at once**:

```
.venv/Scripts/python.exe grid-core/scripts/build_grid_data.py            # rewrite DATA in place
.venv/Scripts/python.exe grid-core/scripts/build_grid_data.py --check    # per-client counts, no write
```

The script re-reads Central2.xlsx and rewrites the single `DATA` line; the
column→key mapping is pinned in `COLS` at the top of the script. It **also
re-anchors the grid's pacing `SNAP` date** in `the-grid.html` to the sheet's real
"as of" date, which it recovers from the `% Flight Elapsed` column
(`asof = start + pctElapsed × (end − start)`, median across all mid-flight rows) —
so run-rate projections always match the sheet instead of drifting from a stale
hardcoded date. One run keeps both the campaign list and the pacing math in sync.

### Live metrics from BigQuery (the scraped half)

The plan: the **commercial** columns (budgets, targets, margins, owners, flight
dates, notes) stay manually typed; the **metric** columns (spend / impressions /
clicks) are scraped live. `scripts/live_metrics.py` is the scraped half — it reads
the same BigQuery layer that powers the client dashboards (so the grid matches the
dashboards number-for-number) and, during a `build_grid_data.py` run, **overlays
those live numbers onto the sheet-seeded rows**. Overlaid rows are tagged
`metricsSource:'BQ'` (+ `dataThrough`) and show a **LIVE** badge in the grid;
everything else stays `'sheet'`. A BQ hiccup never blocks the regen — rows just
fall back to sheet numbers. Skip the overlay with `--no-live`.

**Coverage is explicit and validated, never guessed.** Only advertisers with a
reconciled entry in `CLIENTS` (in `live_metrics.py`) are scraped. Add a client by
adding its per-campaign BQ spend query + a `program → grid campaign` map. Today
Schneider is wired (via `client_schneider.pm_delivery`). Requires `bq` CLI auth as
`ian@100.digital`.

**BigQuery is the source of truth for spend — not the sheet.** BQ spend is RAW
media spend (platform cost + FX only; e.g. schneider TradeDesk `spend_aud =
COSTS × 1.50`, **no** client-billing multiplier). The **sheet's** "Client Spent"
column carries a manual billing multiplier (and its "Media Spend" drifts), so
sheet-vs-BQ will diverge by design — that is expected, not a bug, and the grid
intentionally shows the raw BQ number (decision 2026-07-09: "just reflect BQ").
`tmp/reconciliation.csv` (written each run) is kept as a diagnostic, but the real
trust gate for a new platform is **BQ vs the platform UI**, not BQ vs the retiring
sheet. If a billed view is wanted later, apply the per-channel multiplier on top of
the raw BQ spend (same markup the dashboards use) rather than trusting the sheet.

## Go-live path (in order)

1. `cp .env.example .env` and fill in whatever credentials you have.
2. Run the **probe** (the earlier `api-probe` project) to get the GREEN/YELLOW/RED
   access map. Anything landing at stage `enablement` (TTD) → email your rep the
   same day; that clock runs independent of code.
3. For each GREEN/YELLOW platform, run **reconciliation** before trusting it:
   ```
   node src/reconcile.js --expected expected.json --asof 2026-06-26
   ```
   Fill `expected.json` with one campaign's spend/impressions read straight off
   the platform UI. A clean 1,000,000× or 100× ratio in the output is a units bug
   (e.g. Google `cost_micros` not divided) — fix it in that connector, re-run.
4. Once a platform reconciles to the cent, point the dashboard's data source at
   `orchestrator.fetchLiveCampaigns()` for that source. Others stay on the sheet
   until they reconcile. Migrate one platform at a time.

## Connector contract

Every connector exports:
```js
async function fetchReport({ env, start, end }) => RawRow[]
```
- Returns rows in the shape `normalizedRow()` defines (identical to derive's input).
- Throws `ProbeError(stage, message)` where stage ∈
  `auth | scope | data | enablement | config | network`.
- **Read-only.** No mutate/write calls. (TTD/Reddit reporting POSTs are reads.)
- CREATE-POLL platforms hide their define→run→poll→download loop *inside*
  `fetchReport()` so the orchestrator just awaits an array — see `trade-desk.js`.

## Known data-parsing flags (only affect values, not reachability)

- **Google Ads**: `cost_micros / 1e6`; API version may need bumping (`GOOGLE_ADS_API_VERSION`).
- **Reddit**: report field names + spend scaling need confirming against a live response.
- **TTD/DV360**: report *column* names depend on your saved template; map in the
  connector's parse function once you see a real report.

These are exactly what step 3 (reconciliation) is designed to catch.

---

# Brain (V1)

**Brain** is a tab in The Grid that surfaces AI-recommended campaign optimizations
across every client in one ranked, cross-client view — "here are the highest-impact
changes we could make right now, with the evidence behind each one." A trader reviews
a recommendation, and one click sends it to ClickUp for a human to action.

## Where it lives

A tab in the top nav (Pulse · Register · **Brain** · Executive), next to a small
`NEW` badge. The Grid is a single static HTML app with **hash-based routing**, so:

- `#view=brain` — the cross-client landing page
- `#view=brain&r=R-2847` — the evidence drill-down for one recommendation

(The original spec referred to path routes `/d/brain/` and `/d/brain/r/:id`. The Grid
has no server and already routes on the URL hash, so Brain follows that convention.
Direct-URL load, refresh, and browser back/forward all work because the app re-reads
the hash on `hashchange`.) Filter state is persisted to the hash too, `b`-prefixed so it
never collides with the pacing filters: `#view=brain&bc=resetdata&bp=Trade%20Desk&bconf=0.75`.

## V1 scope (this session) — what's real vs mocked

Real: routing, the full landing + drill-down UI, filtering/sorting, URL persistence,
client colours, keyboard shortcuts, toasts, loading/empty/404 states, and the
"Send to ClickUp" round-trip.

Mocked:
- **Recommendations data** — `config/brain-mock-data.js` (~30 recs across 8 clients).
  Still hand-authored (no live BigQuery query yet), but as of the V2 data pass it is
  **grounded in the real clients** (see "V2 — data grounding" below).
- **The ClickUp endpoint** — the front-end really does `POST /api/brain/clickup-task`,
  but because The Grid has no server, a `window.fetch` interceptor in `the-grid.html`
  answers it: logs the payload (`[BRAIN][ClickUp]`), mints a `CU-MOCK-xxxxxx` id, flips
  the rec's status to `in_clickup` in the in-memory store, and returns
  `{ success, mock_task_id, updated_at }`. V2 deletes the interceptor and stands up a
  real Express route with the **same contract**.
- **Site Quality Index** and **Optimization log** cards — static content.
- The outperformance chart is **hand-rolled SVG** (The Grid does not bundle Chart.js);
  the day/week/month toggle shows `week` as the live view, day/month are V1 placeholders.

## Keyboard shortcuts

`b` → Brain · `p` → Pulse (pacing) · `Esc` → back to the Brain landing from a drill-down
(ignored while typing in an input/select).

## Where to find things

```
config/kpi-objects/<client>.json   ← per-client KPI object schema (resetdata is real, 7 stubs)
config/brain-mock-data.js          ← RECOMMENDATIONS + helpers (getRecommendationById,
                                       getFilteredRecommendations, updateStatus)
src/brain/client-colors.js         ← getClientColor(clientId[, theme]) -> {bg,fg,border}
src/brain/toast.js                 ← toast.success / toast.error
src/brain/brain-landing.js         ← BrainLanding.render(mount, ctx)  (KPIs, filters, table, cards)
src/brain/brain-evidence.js        ← BrainEvidence.render(mount, ctx) (6-section drill-down + chart)
the-grid.html                      ← nav tab, #view-brain container, Brain CSS (#brain-css),
                                       hash routing, the mock ClickUp fetch interceptor, shortcuts
```

The brain modules are classic scripts (UMD): they attach to `window.*` in the browser and
`module.exports` in Node (so the mock data can be unit-tested with `node`). They're loaded
via `<script src>` in `the-grid.html`, before the main app script.

The seam between the host page and the brain modules is a small `ctx` object the page builds
(`data`, `colors`, `toast`, `theme`, `filters`, `setFilters`, `open`, `back`, `sendToClickup`).

## V2 — data grounding (done)

The mock data was audited against the real clients (`clients/client_<c>/`) and the raw
ingest layer (`ingest/`), so every recommendation is now *faithful* even though it's still
hand-authored:

- **Platform-per-client is real and enforced.** Each client's `CLIENT_META.platforms` lists
  only the ad platforms it actually buys on (e.g. MongoDB & VMCH = Trade Desk only; Cloudflare
  runs LinkedIn/Trade Desk/Reddit/**LINE** but no Meta/DV360; Schneider has no Google Ads; only
  ResetData runs Meta). `rec()` **throws** if a rec is assigned a platform its client doesn't run,
  so the V1 bug (MongoDB on LinkedIn/Meta, etc.) can't come back. The platform mix is therefore
  the *real* one — Trade-Desk-heavy, Meta only on ResetData — not a synthetic even spread.
- **Currency & FX** per client match the dashboards (AUD: resetdata/schneider/vmch/tlm/proptrack;
  USD: mongodb/cloudflare/hireright; TTD USD→AUD @1.50, LINE JPY→USD @155, etc.).
- **Real programs/campaigns** appear in titles (Schneider's Water & Environment / EBA / Heavy
  Industries / Global Rebrand; MongoDB's DNB IDE programmes; Cloudflare's Roverpath/Final Funnel;
  VMCH's RAC/SAH/Disability; TLM's Shopping/Search).
- **Data lineage on every rec** — `data_source` is the real BigQuery table(s) a V2 engine would
  query (`raw_snowflake.tradedesk_apac_all`, `raw_windsor.perf_meta`, `raw_snowflake.linkedin_ads_apac`,
  `raw_google_ads.perf_google_ads`, `raw_snowflake.dv360_apac`, `raw_windsor.perf_reddit`,
  `raw_snowflake.salesforce_cs_apac_all`, …). The KPI objects gained a matching `raw_sources` map.
- **Honest `data_readiness` flag** — ⚠️ the ingest layer has **no per-placement / per-domain / per-site
  breakdown** (Trade Desk stops at campaign×ad_group×creative; Meta at ad×date). So `placement`
  isolations and `site_quality`/MFA recs are tagged `data_readiness: 'needs_ingest'` (7 of 30) and
  render a **"needs placement-level ingest"** badge on the drill-down. The other 23 (`live`) are
  derivable from tables that exist today. This is the single biggest blocker for a real engine.

## V2 roadmap

- **Placement/domain breakdown ingest** (the gating item for `placement` + `site_quality` recs):
  add a per-site/supply-vendor breakdown table from Trade Desk/DV360 (or verify whether
  `raw_snowflake.dv360_apac` / `tradedesk_apac_all` already carry site columns at source).
- Real recommendations engine (BigQuery queries → scored recs) reading each rec's `data_source`,
  replacing the hand-authored `brain-mock-data.js`
- Real ClickUp API (replace the fetch interceptor with a server route + auth)
- LlamaParse ingestion of historical media plans / retros to ground the `historical_pattern`
- Site Quality Index with real scoring (Jounce integration) + a live domain blacklist
- Meridian MMM planning loop feeding budget-shift recommendations
- Cross-client learning (a win on one client raises confidence for the same play elsewhere)
- Model-precision metric computed from shipped-rec outcomes (currently hardcoded 73%)

---

# Central (tab)

**Central** replaces the manual `central.xlsx` "Live Campaigns" tracker with a tab in The
Grid that splits every column into three types and enforces them structurally:
**CONFIG** (from media plans / editable), **API** (synced spend/impressions — read-only),
**DERIVED** (computed, never typed). It fixes the sheet's hardcoded-derived-cell and
divide-by-zero bugs by computing every derived value fresh from `src/central/calc.js` on
each render, with every division guarded to render `—`.

## Files
```
src/central/calc.js          ← derived-field engine (SINGLE SOURCE OF TRUTH). Adds
                                marginDelta / marginBand / health to the base formulas.
config/central-seed.js       ← TEST FIXTURE (render smoke tests only). NOT a runtime source.
config/central-import.json   ← frozen ONE-TIME import source (the pure-sheet parse); the
                                server ingests it into the campaigns DB on boot (idempotent).
config/central-clients.json  ← sync client mapping. Mode A ("view" = a pm_delivery view,
                                Schneider) or Mode B ("source":"raw" = raw platform tables[]
                                with exact advertiserValue + schema column names). source
                                "none" = no BQ presence.
scripts/central_sync.py      ← BQ metrics fetcher (adapter; reuses live_metrics.py's bq-CLI
                                approach, does NOT modify it). Mode A + Mode B (multi-table
                                merge by campaign name). Emits JSON to stdout.
scripts/bq_audit.py          ← READ-ONLY discovery: lists raw_snowflake/raw_windsor tables,
                                reads each schema, finds the real advertiser/campaign/impression/
                                cost column names, and lists advertisers. Mapping table for the config.
src/central/render-central.js← the tab: reads GET /api/central/campaigns (the DB), grouping,
                                colour-coding, live-first filters, sort, dropdowns, Add,
                                archive, sync/export. Holds mapGridRowToCentral() — the ONLY
                                name-translation point (grid `advertiser/…` → calc names).
src/central/plan-panel.js    ← media-plan dropzone + review/commit panel + Add-campaign panel.
src/central/plan-reader.js   ← server-side extraction (SheetJS grid + parser.js text),
                                normalization, header-keyword heuristic, candidate match
                                (against the campaigns DB).
```
Wired into `the-grid.html`: nav button (Pulse | Brain | **Central** | Register | Executive),
`#view-central`, dispatch in `renderContent()`, hash whitelist, `<script src>` tags.

## Data model + persistence — the DB is the SOURCE OF TRUTH
Central's source of truth is the SQLite **`campaigns`** table (in `src/brain/db.js`), NOT the
baked `const DATA` literal and NOT `central-seed.js`. On server boot the pure-sheet parse
(`config/central-import.json`) is imported once into `campaigns` (idempotent guard: skips if
sheet-import rows already exist — it is a one-time import, **not a pipeline**). Traders then
add / edit / end / archive campaigns **in Central directly** — no Excel edit, no script re-run.
Rows have a stable generated `id`, `sourceOfRecord` (`sheet-import|manual|plan`), and
`archivedAt` (soft delete only — there is no hard-delete route). Derived values are computed
fresh per render via `CentralCalc.computeRow()`, never stored. Field edits update the
`campaigns` row (the value) **and** append provenance to `central_rows` (the source/filename/
cellRef, keyed by campaign id). **DERIVED fields are never writable** — `db.js` whitelists
(`CENTRAL_EDIT_FIELDS`, `CENTRAL_PLAN_FIELDS`) and rejects `CENTRAL_DERIVED_FIELDS` everywhere.
(`the-grid.html`'s `const DATA` still feeds Pulse/Register only — Central no longer reads it.)

## Status model + live-first view
Statuses: **Active · Paused · Not Active · Ended · Draft**. Active/Paused/Not Active/Ended come
from the sheet verbatim ("Not Active" is real — never coerced); **Draft** is app-only (new thin
rows + blank-status import). The default view is **live** = Active + Paused + Draft; the chip row
is `Live · Active · Paused · Not Active · Ended · All · Archived` (each with a count) and the
header reads "N live · M total". Ended/Not Active are history, always retrievable, never deleted.

## Sync (live BQ metrics)
"Sync now" `POST /api/central/sync` spawns `scripts/central_sync.py` (30s timeout → 502; a
sync already running → 409), which reads `config/central-clients.json` and queries BQ (bq CLI,
ian@100.digital) per **validated** client. Matching at sync time uses ONLY the explicit map
(no fuzzy — that's reconcile). Per mapped, non-archived, non-Ended (unless `?includeEnded=1`)
campaign it UPDATEs `impressions`/`mediaSpend`, sets `metricsSource:'bq'`+`lastSyncedAt`, and:
- **spendMult set** → `clientSpend = mediaSpend × spendMult`, `spendBasis:'billed'`.
- **spendMult unset** → `clientSpend` UNTOUCHED (keeps its sheet value), `spendBasis:'sheet'`,
  and the row shows LIVE + the unbilled-basis badge ("media spend is live; client spend awaits
  spendMult"). It **never** writes `clientSpend = mediaSpend` (the regression that zeroed
  Schneider margins — encoded as a test). CONFIG columns are never written by sync.
Response: `{syncedAt, updated, perClient, unmatched, skippedClients, errors, rows}` (refreshed
rows so the UI updates without a second fetch). Unmapped BQ names → `unmatched`; validated:false
clients → `skippedClients`. Tests inject `CENTRAL_SYNC_FIXTURE` (a JSON path) so CI needs no BQ.

**Auto-sync (scheduled):** set env `CENTRAL_AUTOSYNC_MIN=<minutes>` (0/unset = off) and the
server runs the sync automatically on that interval — via the SAME guarded core as the manual
route (a tick during a manual sync just skips; a manual sync during a tick gets a 409). The UI
shows "· auto every Nm" next to the last-synced pill (from `/api/central/sync/status`). Manual
"Sync now" always works regardless. (A self-gating "only when BQ advanced" refinement, like the
client dashboards' freshness contract, is a future optimization; v1 is a simple interval.)

## Summary cards + KPI + channels
- **Summary cards** (boss view) above the table: Live campaigns (of total), Total budget,
  Total spend (media, N live · M sheet), Health (winner/watch/steady), BQ coverage (validated
  clients / total, progress bar). Reactive to filters; nulls excluded from sums (never NaN).
- **KPI columns** Key KPI + KPI Performance are hand-typed CONFIG text (editable). KPI Performance
  is colour-coded vs Key KPI where both parse to the same unit (green = meets/beats, red = >30% off;
  ROAS/CTR/Clicks/Leads higher-better, CPL/CPA/CPM/… lower-better). "#DIV/0!" → "—". Display-only —
  never stored. (kpiPerformance was reclassified from a never-implemented DERIVED passthrough to CONFIG.)
- **spend-basis info mark**: a LIVE row whose clientSpend is still sheet-era (no spendMult) gets a
  neutral "i" on the margin cell ("set the billing multiplier for a live margin") — distinct from the
  amber needs-input tint, so a config-gap negative margin reads differently from a real one.
- **Channel chips**: 8 channels (Trade Desk, LinkedIn, Google Ads, Meta, DV360, Reddit, DOOH, LINE),
  matched case/space-insensitively so the sheet's "TradeDesk"/"Linkedin" resolve correctly.

## Per-row match schema (Design A: one row per campaign-per-channel)
A validated Mode B map row is `{ campaignId, channel, advertiserName, campaignMatch: {mode, value} }`
(written by reconcile/approve; `advertiserName` is the BQ-side spelling per row, so quirks like the
trailing space in `"VMCH "`, `"Cityperfume.com.au"`, or the `"PopTrack"` typo are handled per row).
The sync uses ONE rule shape (`src/central/match.js`, no separate rollup path) over the tagged BQ
rows the fetcher returns (each `{bqName, advertiserName, channel, impressions, mediaSpend}`):
- **exact** — campaign name === value (scoped to the row's channel + advertiserName).
- **contains** — campaign name contains value (same scope).
- **rollup** — campaign name contains value, but spans ALL advertiser-name spellings for that channel
  and dedupes by campaign name (the "Always On" case — the same campaign under two account spellings
  counts once). Then sum. The spendMult rule and DERIVED locking are unchanged. Schneider stays Mode A
  (view, `map:[{bqName(program), campaignId}]`) — additive, its behaviour is untouched.

## Coverage expansion (reconcile — Zhen's validation sitting)
Only Schneider is validated today. To add a client: **Map client** panel → pick the client →
GET `/reconcile/:client` runs the BQ name list + fuzzy-scores it against that client's Central
campaigns → the human ticks/approves pairs → POST `/approve` writes them into
`central-clients.json` and flips `validated:true`. Suggestions are never auto-written. A client
needs a `pm_delivery`-shaped BQ view first (reconcile reports an empty name list otherwise).

## Lifecycle (traders manage campaigns in Central)
- **Add campaign** (button by Sync/Export) → panel → `POST /api/central/campaigns`
  (section+client+name required, rest optional, `status:'Draft'`, `sourceOfRecord:'manual'`).
- **Status change** via the status dropdown (how campaigns "finish") — no row removal.
- **Archive** (row action) → `archivedAt` set; hidden except the Archived chip (muted).
- The plan reader's **create-new** path creates a real `campaigns` row (`sourceOfRecord:'plan'`).

## Routes (server.js)
- `GET  /api/central/campaigns` → `{campaigns}` (the DB — Central's data source)
- `POST /api/central/campaigns` → create a thin Draft row (section+client+name; derived → 400)
- `POST /api/central/campaigns/:id/archive` → soft delete (no hard-delete route exists)
- `GET  /api/central/rows` → `{overrides}` (per-field provenance, keyed by campaign id)
- `POST /api/central/row/:id/field` → edit a campaign field (`:id` = campaign id; derived → 400)
- `POST /api/central/sync[?includeEnded=1]` → live BQ overlay (see "Sync" below); 409 if already running
- `GET  /api/central/sync/status` → `{running, autosyncMin, lastRun}` (drives the UI's auto-sync note)
- `GET  /api/central/reconcile/:client` → BQ name list + Central names + fuzzy SUGGESTIONS (never written)
- `POST /api/central/reconcile/:client/approve` → write APPROVED pairs to the map + validated:true
- `POST /api/central/plan/upload` → base64 JSON; extract → PENDING draft → `{fields,candidates}`
- `POST /api/central/plan/:id/commit` → writes USER-CONFIRMED values to `campaigns`; rejects
  unacknowledged overwrites (`acknowledgeConflicts`) and derived fields; create-new → new row
- `POST /api/central/plan/:id/discard`

## Media-plan reader
Drop XLSX/CSV/PDF/DOCX/PPTX → extract CONFIG fields with per-field provenance
(`{value, sheet, cellRef|page, confidence}`) → review panel (match a campaign or create
new; edit any field; low-confidence flagged; conflicts resolved keep/replace, default
KEEP) → commit. Extraction **never** writes a row. Uses Claude when `ANTHROPIC_API_KEY` is
set, else a deterministic header-keyword heuristic (everything `confidence:'low'`); a
PDF/DOC with no LLM key falls through to an empty panel for manual entry — never a dead end.

## Decisions baked in
- **Platform margin is CONFIG**, not API (no connector returns it) — editable, never synced.
- **Client spend = mediaSpend × spendMult**; a row with spend but no `spendMult` shows an
  **"unbilled basis"** badge (billing basis unverified). This fires **widely by design** on
  the real sheet — no row has `spendMult` yet — and clears once it is populated per channel.
- **Join key = (client, campaign-name)**; null `jobNumber` shows a **"no job #"** badge.
- Stale guard: API columns desaturate when `lastSynced` is null or > 4h old.
- **Needs-input tint:** empty manual [CONFIG] cells get a faint amber to-do tint + inline
  edit (dropdown or contenteditable → the whitelisted field route). Never on [DERIVED]
  (their "—" is correct output) or [API] (the sync's job). Agency grouping is
  case-insensitive so the sheet's UPPERCASE agencies group correctly.

## Test
```
node test-fixtures/central/make-central-fixtures.js   # (re)build the messy XLSX fixture
```
Then the two harnesses used during the build exercise the backend (extraction /
normalization / provenance / conflict / derived-rejection) and the render path
(grouping / colouring / filters / sort / null-safety).

---

# Executive (tab)

**Executive** is an at-a-glance, per-client view of the ONE or two **client KPI metrics** that matter
(leads / ROAS / impressions / clicks / enquiries) so a media buyer (or the boss) sees who's performing
and who needs a look without opening each dashboard. It is deliberately **NOT a pacing view** — budget
pacing / margin-at-risk live on Pulse and Central; Executive is the client-outcome lens. It **replaced
the old Dashboards tab** in the top nav (Pulse · Brain · Central · Register · **Executive**). The
per-client "Open dashboard ↗" links the Dashboards tab used to carry are folded into each exec card, and
an "All dashboards ↗" link (the platform front-door) sits in the filter bar. `renderDashboards()` +
`#view-dashboards` remain in the file but are unreachable from the nav (a stale `#view=dashboards` hash
still renders them).

## What it shows (all in `renderExec()` in `the-grid.html`; CSS in the `#exec-css` block)
Per client, one card led by its **main KPI**:
- **Headline KPI** — the metric the client is paid to move (e.g. Accepted CS leads, MQL+HQL, ROAS,
  Impressions, Clicks, Ad-attributed enquiries), with a **trend delta**, a **sparkline**, a **KPI-vs-target
  meter** (where a target exists), and **supporting metrics with context chips** (e.g. "70% Acceptance
  rate · on par with prior", "$150 Cost / lead · 12% over target").
- **Reading toggle (Daily / Weekly / Monthly)** — the trend window; a client can read differently per
  grain (a rough week can be a normal monthly hiccup, a slow bleed shows monthly). Lead clients whose
  data is weekly-only fall back from Daily to Weekly with a note.
- **Verdict** — a deliberately LENIENT 4-level roll-up (On track / Watch / Behind / At risk) in
  `exVerdict(pace,delta)`: with a target, the KPI-to-target pace band nudged by the trend; trend-only
  otherwise. Kept generous so the "Needs attention" list stays trustworthy (no crying wolf).
- **AI "what's happening" note** per client.
Grouped by objective (Acquisition / Awareness & Traffic / Sales), with clickable verdict summary cards +
an agency filter, an **Objective** dropdown (beside the Reading toggle), and a **Sync now** button. Verdict colours are fixed semantic tokens; all surfaces/text
use the grid's own theme vars + Inter/Space Grotesk, so dark/light come for free. `EX_HIDE`-equivalent:
City Perfume + HireRight are simply not in the `EXC` list.

**Data (live seam + preview fallback):** `renderExec()` fetches **`config/exec-kpis.json`** and, if
present, drops it in over the baked `EXC` preview (`EX_SRC` -> `'live'`; the hero relabels and shows the
build date); absent/offline it stays on the labelled preview, so the tab always renders. That file is
produced by **`scripts/build_exec_kpis.py`**, which reads each client's own `data.json` from GCS
(`gs://bidbrain-analytics-<c>-dash/<c>.json` - the exact JSON the dashboard serves, built from BigQuery,
so exec == dashboard to the digit) and extracts the headline KPI + target + daily/weekly/monthly trend +
supporting metrics in the `EXC` shape. Run it with ADC creds (`gcloud auth application-default login` as
ian@100.digital or a key with objectViewer on the client buckets):
```
.venv/Scripts/python.exe grid-core/scripts/build_exec_kpis.py --check   # print extracted numbers, no write
.venv/Scripts/python.exe grid-core/scripts/build_exec_kpis.py           # write config/exec-kpis.json
```
Each client extracts in its own try/except (a failure is SKIPPED, so its preview card stays), and the
per-client paths should be VALIDATED against the dashboards on the first creds run (a couple of nested
daily-array field names are flagged `#VERIFY`). The Sync button re-fetches the file once it's live.

**Verify without a browser:** `exec-verify.js` (this session's scratchpad) stubs the DOM in a `vm` context,
runs the main script, calls `renderExec()`, prints the per-client KPI/verdict table, and writes a
green-themed HTML snapshot.

**Roadmap:** validate + schedule `build_exec_kpis.py` (or fold it into `build_grid_data.py` / a
Central-style sync) so `config/exec-kpis.json` refreshes automatically; AI-written notes (Gemini/Vertex,
like Central's plan reader) can replace the computed `_note`.
