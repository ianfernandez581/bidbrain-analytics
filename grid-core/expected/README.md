# expected - The Grid, Expected side (plan baseline)

Turns a media buyer's campaign file dump into the expected-side baseline the
Actual side compares against. First campaign: Schneider Electric NEL Awareness,
Job 2053 (ANZ, AUD 35,000, flight 2026-06-01 to 2026-08-22, TradeDesk 8,000 +
LinkedIn 27,000 split Video 6,000 / Doc Ads 14,000 / SIA 7,000).

## Build

```
node grid-core/expected/build_expected.js
```

Regenerates everything in `out/` from plan constants extracted from the source
files (each constant cited in the script header and the xlsx Info sheet). All
arithmetic is plain code: daily = goal / days, cumulative = days elapsed /
total days x goal, 83 days inclusive. Final-day cumulatives equal the plan
goals exactly; the script throws if the campaign budgets stop summing to 35,000.

## Outputs (out/)

- `daily_kpi.xlsx` - one row per campaign per day: daily + cumulative spend,
  impressions, clicks. Info sheet carries goals and per-number citations.
- `daily_kpi.json` - same numbers from the same rows array, one source of
  truth. Shape: `{job, client, currency, generated_at, campaigns[{campaign_name,
  platform, start, end, total_budget, goal_impressions, goal_clicks, daily[]}]}`.
- `pacing.html` - self-contained pacing page: cumulative expected line per
  campaign, metric toggle, today marker, hover readout. Actuals join hook for
  the Actual side: set `window.BB_ACTUALS` or call `joinActuals(rows)` with
  daily `{date, campaign, spend, impressions, clicks}` rows.
- `flowchart.html` - self-contained stage flowchart (Request Received through
  Pacing), colored from the report items.
- `report.md` - 15 gaps and inconsistencies found in the source files, each
  citing its source file and sheet.
- `chase_messages.md` - draft messages (one per recipient) requesting each
  missing item. A person reviews and sends.

## Notes

- The source file dump (media plan, setup sheets, creative sheets, TAL lists,
  creative assets) is NOT committed; it lived at `grid-core/files/` locally.
- Extraction of the plan constants was a hand-verified model pass this session;
  automating extraction (Claude API, structured output, citations) is the next
  milestone, as is a UI server (in progress locally, not yet shipped).
- Flight-date note: every source document says "82 days" but the June window is
  83 days inclusive (report.md item 2). The baseline uses 83.
