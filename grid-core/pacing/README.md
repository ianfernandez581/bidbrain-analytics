# Pacing engine

Pure function. No database, no clock, no dependencies. Every pacing figure the
Grid displays should come from here, so that a number appearing twice on screen
was computed once.

## Run the tests

```
node --test pacing.test.js
```

15 tests, all passing. Fixtures are real campaigns with verdicts supplied by the
media buyer. The buyer's judgement is the assertion.

## Use

```js
const { computePacing, profitAtRisk, rollUp } = require('./pacing');

const r = computePacing({
  budget: 15000,
  budgetBasis: 'client',        // 'client' or 'media'. Must be explicit.
  currency: 'AUD',
  platform: 'ttd',
  level: 'adset',               // display only
  plannedStart: '2026-07-29',
  flightEnd: '2026-10-29',
  dailySpend: [{ date: '2026-07-29', amount: 195.25 }, /* ... */],
  asOf: '2026-08-03'            // treated as today, always excluded
});

profitAtRisk(r, 0.60);          // margin is a per-platform fact
```

## States

| State | Meaning |
|---|---|
| NOT_LAUNCHED | Flight has started, nothing has delivered |
| TOO_EARLY | Not enough delivery days to judge pacing |
| ON_TRACK | Within the drift band |
| TOO_FAST | More than the band ahead. Will exhaust early |
| BEHIND_RECOVERING | Behind, but the current rate covers what is required |
| BEHIND_NOT_RECOVERING | Behind, current rate insufficient, still reachable |
| UNREACHABLE | Required daily exceeds the best rate ever observed. Structural |
| ENDED | Flight is over |

`deadDayFlag` is reported alongside every state. A campaign can have launched a
month late and still be catching up, so it is a separate signal rather than a
replacement for the pacing state.

## Decisions baked in

**Today is always excluded.** Platform days are partial until the account
timezone rolls over. Comparing a partial day of spend against a full day of
target understates pace, and the distortion is largest when a campaign is
newest. On a 5-day-old campaign it is worth 20%.

**The schedule always runs to the fixed end date.** A late launch does not earn
a lenient target. The end date has not moved, so the same money must be spent in
fewer days and required daily goes up. Anchoring the schedule to first spend
would have reported job 2463 as ahead of pace after 31 dead days.

**Drift is measured in days of budget, not percent.** A fixed percentage band
is wrong early in flight, when one good day moves a pace index by 20%. Drift in
days self-scales, and it explains itself in one sentence, which matters when the
audience wants short answers.

**Rate and capacity use delivery days only.** A spend rate across days with no
delivery is meaningless.

**Peak rate is a rolling three-day mean.** One spiky day is not capacity. Below
three delivery days it falls back to even pace and sets `peakIsFallback`.

**Projections are capped at budget and carry a confidence level.** Projecting
from two delivery days across 120 remaining days produces numbers three times
the budget. Low confidence below 7 delivery days.

**Margin affects profit, not pacing, on platforms that report gross.** TTD with
platform margin configured reports cost gross of margin, so pace against the
client budget. Haircutting the budget by 60% turns a healthy Caltex campaign
into one apparently burning 3x too fast. `budgetBasis` is required so this can
never be ambiguous.

## Configurable thresholds

Override per call via `thresholds`. These belong in a database table, not in
code, so a media buyer can tune them without a deploy.

```
driftDaysBand      3       days ahead or behind before leaving ON_TRACK
minDeliveryDays    3       no verdict below this
minFlightFraction  0.05    and not before this share of flight elapsed
recentWindow       3       complete days in the recent rate
peakWindow         3       rolling mean width for peak rate
reachTolerance     1.15    required may exceed peak by this and stay reachable
deadDayThreshold   2       zero-delivery days before flagging
```

## Still needed

Fixtures marked RECONSTRUCTED spread an aggregate evenly across days because
only a total was available. Figures depending on the shape of the series
(recentRate, peakRate) are not asserted on those. Replace with the real daily
series from BigQuery and the assertions get stronger.

The 19-dollar incident fixture uses placeholder dates and budget. Replace with
the real campaign.
