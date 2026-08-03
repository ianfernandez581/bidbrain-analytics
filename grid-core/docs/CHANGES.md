# Pacing engine v2

Drop all three files into `grid-core/pacing/`, replacing the two that are there.

```
node --test pacing/pacing.test.js      # expect 21 pass, 0 fail
node pacing/compare-pacing.js          # report only, writes nothing
```

## What changed

**Degraded mode.** The engine no longer requires a daily series. Pass
`spentToDate` plus `lastDataDate` and it returns pace index, drift in days,
required daily and reachability. Dead days, recent rate and peak rate come back
`null` with a stated reason rather than being invented.

This matters because `central_sync.py` collapses the daily grain with
`GROUP BY 1` before anything is stored, so no daily series exists yet. Verified:
degraded mode reaches the same UNREACHABLE verdict on Water and Environment as
full mode does. Pulse can be correct today, before the ingest changes.

**Basis vocabulary follows `plan-reader-v2-design.md`.** `spendBasis` takes
`media`, `billed` or `unknown`. `client` is accepted as a synonym for `billed`.
An `unknown` basis returns `BASIS_UNKNOWN` and refuses to produce a verdict,
matching R1's rule that a human must choose.

**Margin resolves from the platform, never from a row.** `PLATFORM_RULES` holds
TradeDesk at 60% and everything else at zero. Central carries
`platformMargin = 0.006` on Caltex where 0.6 was meant; reading margin per row
lets one typo corrupt one campaign by 100x.

**No conversion, anywhere.** Every platform's stored figure is billed, either
because it reports billed (TradeDesk, verified twice to the cent) or because
margin is zero so media equals billed. `spendMult` is not consulted.

**Drift in days, not a percentage band.** A fixed percentage is wrong early in
flight, where one good day moves a pace index 20%. Days of drift self-scale and
explain themselves in one sentence.

**Ramping flag.** When the latest day exceeds the 3-day peak by 2x, the campaign
is accelerating and is not declared unreachable. Job 2463 reads unreachable today
and clears within two days; without this, people learn to distrust the alert.

**Staleness flag.** `dataAgeDays` and `stale`, tripping past 3 days to match the
existing as-of badge. A stale verdict is not a current verdict.

**Currencies are never summed.** `rollUpByCurrency` returns one aggregate per
currency. The Grid currently adds AUD, USD and SGD into one profit-at-risk
figure.

**Profit at risk returns `{ value, marginUsed, estimated: true }`.** Always
labelled an estimate, because on TradeDesk the fee card reads "60% of partner
cost" while billed also carries per-impression ad serving and audience data fees.
Observed billed-to-partner on Caltex was 8.16x where margin alone predicts 1.6x.
A margin of 1 or more throws rather than clamping.

## Thresholds

All overridable per call via `thresholds`. They belong in a database table so a
media buyer can tune them without a deploy.

```
driftDaysBand           3      days ahead or behind before leaving ON_TRACK
minDeliveryDays         3      no verdict below this
minFlightFraction       0.05   and not before this share of flight elapsed
recentWindow            3      complete days in the recent rate
peakWindow              3      rolling mean width for the peak
reachTolerance          1.15   required may exceed the rolling peak by this
reachToleranceDegraded  3      wider, an average is a weaker ceiling than a peak
rampMultiple            2      latest day this far above peak means accelerating
staleDataDays           3      matches the as-of amber badge
deadDayThreshold        2      zero-delivery days before flagging
```

## Still open

Daily series at ad-group grain. Until then `capacityBasis` is
`observed_average` rather than `rolling_peak`, dead days are unavailable, and
the ramping flag cannot fire.
