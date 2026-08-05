# Greenlight — plan and backlog docs

> Greenlight is the campaign-readiness feature inside `grid-core`: upload a client's raw campaign
> material, run one cited Claude extraction plus deterministic validators, and get an audit
> (findings, report, flowchart), a daily KPI pacing plan, and chase drafts. It ships feature-flagged
> OFF (`GREENLIGHT_ENABLED`) and lives in `grid-core/expected/` (pipeline) and
> `grid-core/src/greenlight/greenlight.js` (Grid tab).

This folder is the working home of the **Greenlight backlog v2** (revised 2026-08-05, after the dev
prototype landed on main, `ed2bcfe` → `990712c`). It supersedes v1 of the workbook and the
plan-reader v2 epic. These are living plan docs — keep them current as scope moves; they are not a
narrative record of work done (per the repo's docs rule, see GL-22).

## What's in this folder

| File | What it is |
|------|------------|
| [plan.md](plan.md) | The detailed plan: milestones, epics, sequencing, dependency graph, owner split. |
| [backlog.md](backlog.md) | All 28 issues in full — description, acceptance criteria, notes, dependencies, suggested branches. |
| [github-setup.md](github-setup.md) | Instructions: how the backlog becomes GitHub issues, labels, milestones and the Projects v2 board. |
| [stage-spec.md](stage-spec.md) | The six shipped stages from `rulebook.json` and the evidence each one reads. |
| [platform-checklist.md](platform-checklist.md) | Draft per-platform required-asset matrix feeding GL-15. |
| `greenlight-issues.json` | Machine-readable source `create-greenlight-backlog.ps1` reads. If it disagrees with the md files, the JSON wins. |

## Where the backlog stands (v2, 2026-08-05)

The lean set is **28 issues**: 23 Greenlight plus 5 adjacent-debt fixes the feature would otherwise
inherit. GL-28 (the client-material upload path) is already in progress on a dev branch. Placement
is decided: Greenlight stays inside `grid-core` — self-contained and flag-gated — not a separate repo.

| Priority | Count | | Milestone | Issues | Due |
|----------|-------|-|-----------|--------|-----|
| P0 Critical | 2 | | M1 Greenlight Hardening | 10 | 2026-08-11 |
| P1 High | 14 | | M2 Actual Side — Pacing vs API Data | 8 | 2026-08-25 |
| P2 Medium | 9 | | M3 Inputs and Checklist | 6 | 2026-09-08 |
| P3 Low | 3 | | M4 Rollout and Docs | 4 | 2026-09-22 |

## What changed since v1

- **Greenlight exists.** `grid-core/expected/` is the pipeline (preprocess → one cited Claude
  extraction → deterministic validators → outputs) and `src/greenlight/greenlight.js` is the Grid
  tab, feature-flagged OFF (`GREENLIGHT_ENABLED`).
- **Both meeting outputs are already built:** the audit (`findings.json`, `report.md`,
  `flowchart.html`) and the daily KPI pacing plan (`daily_kpi.xlsx`, `pacing.html`). Chase drafts
  too (`chase_messages.md`).
- **The stage set is the shipped six stages** from `rulebook.json`: Request Received, Media Plan
  Approved, Raw Materials Complete, Campaign Built, Live, Pacing. The v1 ten-card spec is superseded.
- **The plan-reader v2 epic (19 tickets in v1) is superseded** by Greenlight's extractor. The one
  surviving sliver is a display-only Central chip (GL-21). Committing extracted values into Central
  stays explicitly out of scope for now.
- **The regression gate runs the Schneider NEL 2053 pilot:** 13/13 green on 2026-08-04. The pilot
  campaign from the meeting is already in place.

## Team and owners

Assignee suggestions follow this split; swap freely on the issues themselves.

| Person | Focus | Issues |
|--------|-------|--------|
| Ian (`ianfernandez581`) | AI / extraction pipeline, repo and deploy identity | GL-01 02 03 08 10 14 |
| Charles (`100charles`) | Dev lead. Uploads of client materials + media-plan outputs; AI with Ian | GL-28 12 13 15 19 20 |
| Jerome (`Jerome072902`) | Tickets/PM. Endpoints; AI support (lighter than Ian/Charles) | GL-04 09 17 18 |
| Juan (`delacruz-juan-agora`) | UI + endpoints | GL-06 07 11 16 21 23 |
| Christian (`KurisuuChan`) | UI + endpoints; docs and ops hygiene | GL-05 22 24 25 26 27 |

## Sources of truth

1. `greenlight-backlog-v2.xlsx` — the editable workbook (edit here first).
2. `greenlight-issues.json` (this folder) — regenerated or hand-edited to match the workbook;
   what the creation script reads.
3. GitHub — once created, the issues and the **Greenlight** Projects v2 board on
   `ianfernandez581/bidbrain-analytics` are where day-to-day state lives.

See [github-setup.md](github-setup.md) for the exact workflow.
