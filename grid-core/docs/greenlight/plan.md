# Greenlight — the detailed plan

> Four milestones, five epics, 28 issues, five people. This page is the plan view: what each
> milestone means, what "done" looks like, in what order the work has to happen, and who owns what.
> The full issue text lives in [backlog.md](backlog.md).

## The shape of the work

The prototype already does the hard part: a client dump goes in, one cited Claude extraction plus
deterministic validators run, and out come the audit (findings, report, flowchart), the daily KPI
pacing plan, and chase drafts. The plan takes that from "works on a dev branch, flag off" to
"on for real buyers, joined to real delivery data, provably client-agnostic":

1. **M1 Hardening** — make what shipped production-safe and turn it on.
2. **M2 Actual side** — join daily BigQuery actuals into the pacing plan; the sixth stage
   (Pacing) gets a real on/behind/ahead verdict.
3. **M3 Inputs and checklist** — conversations (Teams/Fathom transcripts) become citable sources,
   the per-platform required-vs-missing asset checklist lands, findings deep-link to their sources,
   and the two known false-positive families get fixed.
4. **M4 Rollout** — a second pilot on a different agency's format proves client-agnosticism,
   in-flight campaigns get backfilled analyses, Central gets a display-only chip, docs catch up.

An **adjacent-debt** epic (5 issues) rides along: pre-existing defects the feature would otherwise
inherit — silent ingest failures, unguarded truncates, a hardcoded backfill end date, committed
client raw material, stale onboarding docs.

## Milestones

### M1 — Greenlight Hardening (due 2026-08-11, 10 issues)

Make what shipped production-safe: background extraction, repo hygiene, CI, flag-on. Matches the
meeting's "build this week".

**Done when:** `GREENLIGHT_ENABLED=true` on the live service, extraction survives Cloud Run
timeouts, no client raw material tracked in git, CI green.

| ID | Title | Pri | Est | Owner |
|----|-------|-----|-----|-------|
| GL-01 | Move Greenlight extraction to a background job | P0 | M | Ian |
| GL-02 | Purge committed client raw material and fix the ignore policy | P0 | M | Ian |
| GL-03 | Enable Greenlight on the live Grid (flag, secret, bucket, smoke run) | P1 | S | Ian |
| GL-04 | CI workflow: run the test suites; regression gate on demand | P1 | M | Jerome |
| GL-05 | Close the drift inside expected/README.md | P2 | XS | Christian |
| GL-06 | Wire dashboard JS validation into the sanity gate | P2 | S | Juan |
| GL-07 | Surface run cost and duration in the run history | P3 | XS | Juan |
| GL-23 | Guard the HubSpot deals truncate against an empty response | P1 | XS | Juan |
| GL-27 | Fix the dead clone URL and stale client list in ONBOARDING.md | P3 | XS | Christian |
| GL-28 | Finish the client-material upload path (byte staging into the analysis dump) | P1 | M | Charles — **in progress** |

The two P0s lead. GL-01 unblocks GL-03 (a live run that outruns the request timeout kills the
smoke test); GL-02 must happen before the repo accumulates more raw client material — history is
still shallow enough that removal is real. GL-28 is the gate for everything a buyer touches:
uploads are the only way client material reaches a production analysis.

### M2 — Actual Side: Pacing vs API Data (due 2026-08-25, 8 issues)

Join daily BigQuery actuals into the pacing plan and light up the Pacing stage. The meeting's
Output 2, second half.

**Done when:** `pacing.html` draws expected vs actual lines for the NEL pilot; the Pacing stage
shows a real on/behind/ahead verdict; unmatched delivery raises a finding.

| ID | Title | Pri | Est | Owner |
|----|-------|-----|-----|-------|
| GL-08 | ADR: actuals data contract and campaign matching for the Pacing join | P1 | M | Ian |
| GL-09 | Actuals feed: daily platform actuals endpoint per analysis | P1 | L | Jerome |
| GL-10 | Campaign matching: plan names to warehouse names, unmatched raises a finding | P1 | M | Ian |
| GL-11 | Join actuals into pacing.html and persist the joined snapshot | P1 | M | Juan |
| GL-12 | Pacing stage verdict in the flowchart | P1 | M | Charles |
| GL-13 | Pacing variance findings with rulebook tolerances | P2 | S | Charles |
| GL-24 | Ingest loaders must fail the run when BigQuery loads fail | P1 | S | Christian |
| GL-25 | Derive the DTS backfill end date instead of hardcoding it | P2 | XS | Christian |

The ADR (GL-08) comes strictly first — it decides the source table per platform, the join grain,
currency handling, and the campaign-name matching rule. The design constraint that governs
everything here: **campaign names are not stable keys** (Transmission prefixes brief numbers onto
names mid-flight); matching must reuse `src/central/match.js` semantics, never raw-name equality.
GL-24/25 belong in this milestone because Pacing goes stale silently if the loaders lie about
success.

### M3 — Inputs and Checklist (due 2026-09-08, 6 issues)

Conversations receiver (Teams/Fathom), the per-platform required-vs-missing asset checklist,
finding-to-source deep links, and the two known false-positive fixes.

**Done when:** a Fathom transcript is a citable source; every platform on the plan shows required
vs present assets; clicking a finding opens its source.

| ID | Title | Pri | Est | Owner |
|----|-------|-----|-----|-------|
| GL-14 | Conversations receiver: transcripts as citable sources | P1 | L | Ian |
| GL-15 | Per-platform required-vs-missing asset checklist | P1 | L | Charles |
| GL-16 | Finding-to-source deep links in the tab | P1 | M | Juan |
| GL-17 | Scope UTM checks to ad destinations | P2 | S | Jerome |
| GL-18 | Referenced-files matching: kill the false 'unreferenced asset' flags | P2 | S | Jerome |
| GL-26 | Add guards to the production table truncate scripts | P2 | XS | Christian |

GL-15's requirements matrix starts from [platform-checklist.md](platform-checklist.md) — confirm
with the media team before lifting into `rulebook.json`. GL-17/18 matter for trust: false positives
erode the audit faster than missing features do.

### M4 — Rollout and Docs (due 2026-09-22, 4 issues)

Second pilot on a different agency's format, backfill across in-flight campaigns, Central linkage
chip, docs current.

**Done when:** two pilots green in the regression gate, every in-flight campaign has an analysis,
AGENTS.md and both READMEs describe reality.

| ID | Title | Pri | Est | Owner |
|----|-------|-----|-----|-------|
| GL-19 | Second pilot: a different agency's format end to end | P1 | L | Charles |
| GL-20 | Backfill analyses for in-flight campaigns and triage the findings | P2 | L | Charles |
| GL-21 | Greenlight status chip on Central rows | P3 | M | Juan |
| GL-22 | Docs: AGENTS.md, grid-core/README.md and expected/README.md reflect the shipped feature | P2 | S | Christian |

Rollout discipline: a false green found in GL-20's triage **blocks wider rollout until fixed**.
GL-21 is display-only linkage — no Greenlight code path writes into Central; committing extracted
values into Central stays out of scope until rollout proves the extraction trustworthy.

## Dependency graph

Everything not shown below is independent and can start any time within its milestone.

```
M1                         M2                                M3            M4
GL-01 ──► GL-03 ───────────────────────────────────────────────────► GL-19 ──► GL-20 ──► GL-22
                           GL-08 ──► GL-09 ─┐
                           GL-08 ──► GL-10 ─┴► GL-11 ──► GL-12 ──► GL-13
                                                          GL-14 ──► GL-16
```

Critical path to a live, actuals-joined Pacing stage: **GL-01 → GL-03** (feature on) in parallel
with **GL-08 → (GL-09, GL-10) → GL-11 → GL-12**. GL-28 has no formal dependents but functionally
gates every production analysis (it is how client bytes get in), so it stays in-progress work,
not backlog.

## Epics

| Epic label | Scope | Issues |
|------------|-------|--------|
| `epic:greenlight-hardening` | Make the shipped prototype production-safe. | GL-01..07, GL-28 |
| `epic:actual-side` | Pacing vs API data: join BigQuery actuals. | GL-08..13 |
| `epic:inputs-checklist` | Conversations receiver, platform asset checklist, tuning. | GL-14..18 |
| `epic:rollout` | Second pilot, backfill, linkage, docs. | GL-19..22 |
| `epic:adjacent-debt` | Pre-existing defects the feature would otherwise inherit. | GL-23..27 |

## Standing rules the plan assumes

- **Null, never guess:** a value the pipeline can't source stays null with candidates and a
  resolution rationale; no figure renders without a source — remove the element rather than show a
  placeholder.
- **Campaign names are not stable keys.** Brief-number prefixes get stripped once, then
  `match.js` semantics; fixed-offset or exact-name matching has silently dropped delivery twice.
- **Client-agnostic by construction:** format gaps become rulebook/prompt fixes, never client-named
  code in `expected/` (GL-19 greps to prove it).
- **BigQuery via the client library**, never the `bq` CLI (it is not in the image).
- **No Express:** `server.js` stays plain `node:http`.
- **Docs update in the same change** that makes them stale (definition of done); no narrative
  summary md files about work done.
- **Runs cost real money** (~USD 1, 5–7 minutes each): the re-run guard stays, and cost/duration
  become visible (GL-07).

## Dates

M1's due date matches the meeting's "build this week". Overwrite milestone dates with real sprint
boundaries when the team sets them — the workbook, the JSON and GitHub milestones should move
together.
