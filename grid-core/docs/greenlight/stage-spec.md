# Stage spec — the six shipped stages

> The stage set Greenlight ships today, as defined in `grid-core/expected/rulebook.json`. This
> supersedes the v1 ten-card spec. Colour semantics: **green** = ready; **yellow** = open items,
> not blocking; **red** = the stage's defining artifact is missing.

Each stage answers one question about a campaign, reads specific evidence from the analysis dump,
and produced real findings on the Schneider NEL 2053 pilot (the "screenshot examples" below are
actual pilot findings, kept here as ground truth for what each stage is supposed to catch).

## 1. Request Received

**Means:** the brief exists and its commercial asks are internally consistent.

**Evidence it reads:** brief document; extracted budget, KPI, fee treatment vs the media plan.

**Real findings from the NEL pilot:** budget gap (brief $30K vs plan $35K); KPI gap (brief wants
leads, plan buys impressions); fee treatment stated nowhere.

## 2. Media Plan Approved

**Means:** a client sign-off exists on record and the plan's own math holds.

**Evidence it reads:** sign-off evidence; plan header vs flight dates; stated duration math;
superseded/legacy sheets.

**Real findings from the NEL pilot:** no sign-off on record for the $35,000 plan; header prints
the dead April flight; 82 vs 83 day duration error; legacy sheets from another campaign in the
workbook.

## 3. Raw Materials Complete

**Means:** every asset the plan needs has arrived, is approved, and is accounted for.

**Evidence it reads:** manifest of received files with code-measured media metadata; approval
fields; referenced-vs-present reconciliation.

**Real findings from the NEL pilot:** no recorded approval for statics/videos/SIA images; scope
moved 5 lead-gen forms to 3 with no recorded decision; unreferenced NECA-amended PDF;
duplicate/superseded files in the dump.

## 4. Campaign Built

**Means:** what was built in the platforms matches the plan.

**Evidence it reads:** setup/build sheets vs plan: budget labels vs campaign sums, UTMs, geo ids,
platform minimums.

**Real findings from the NEL pilot:** $35,000 label over campaigns summing $27,000; UTMs split
across April and June vintages; NZ carries AU ids; 3 NZ campaigns under LinkedIn's $10/day floor.

## 5. Live

**Means:** delivery is measurable from day one.

**Evidence it reads:** tracking test confirmation (insight tag / pixel), conversion measurability.

**Real findings from the NEL pilot:** Insight Tag test unconfirmed (partner id cited);
conversions may be unmeasured mid-flight.

## 6. Pacing

**Means:** actual delivery tracks the daily plan.

**Evidence it reads:** `daily_kpi` expected rows joined with BigQuery actuals (lands in M2);
tolerance breaches become findings.

**Status today:** expected-only — `pacing.html` ships with the `joinActuals` hook awaiting the M2
actuals feed (GL-09..13).
