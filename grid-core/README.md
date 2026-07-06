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

A tab in the top nav (Pulse · Register · **Brain** · Dashboards), next to a small
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
  No BigQuery yet.
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

## V2 roadmap

- Real recommendations engine (BigQuery queries → scored recs), replacing `brain-mock-data.js`
- Real ClickUp API (replace the fetch interceptor with a server route + auth)
- LlamaParse ingestion of historical media plans / retros to ground the `historical_pattern`
- Site Quality Index with real scoring (Jounce integration) + a live domain blacklist
- Meridian MMM planning loop feeding budget-shift recommendations
- Cross-client learning (a win on one client raises confidence for the same play elsewhere)
- Model-precision metric computed from shipped-rec outcomes (currently hardcoded 73%)
