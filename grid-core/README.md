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
