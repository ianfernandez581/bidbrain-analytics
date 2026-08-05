# How the backlog becomes GitHub

> Instructions for creating (and re-running) the Greenlight backlog on GitHub: labels, milestones,
> all 28 issues, and the Projects v2 board — idempotently, from one script.

## The one command

Run `create-greenlight-backlog.ps1` (delivered alongside the workbook) from any machine where `gh`
is authenticated with **repo + project scopes**:

```powershell
gh auth status                        # confirm scopes include repo, project
.\create-greenlight-backlog.ps1      # reads greenlight-issues.json from the same folder
```

It reads [`greenlight-issues.json`](greenlight-issues.json) and idempotently creates:

1. the 23 **labels** (priority, type, area, epic, status dimensions),
2. the 4 **milestones** with due dates,
3. all 28 **issues** — title, body (description + acceptance criteria + notes + dependencies +
   suggested branch), labels, milestone, assignee,
4. the **"Greenlight" Projects v2 board**, then adds every issue to it.

**Safe to re-run:** existing items are skipped, never duplicated.

Target repo (from the JSON): `ianfernandez581/bidbrain-analytics`.

## Auto-assignment

GitHub usernames are baked into the script's `$UserMap`, so issues auto-assign on creation:

| Hint | GitHub username |
|------|-----------------|
| ian | `ianfernandez581` |
| charles | `100charles` |
| jerome | `Jerome072902` |
| juan | `delacruz-juan-agora` |
| christian | `KurisuuChan` |

Swap owners freely afterwards on the issues themselves.

## The editing workflow

The workbook is the editing surface; the JSON is what the script reads; GitHub is where live state
ends up. Keep them moving together, in this order:

1. Edit `greenlight-backlog-v2.xlsx` (the Issues sheet's Description + AC + Notes columns become
   the GitHub issue body).
2. Regenerate — or hand-edit — `greenlight-issues.json` to match.
3. Re-run `create-greenlight-backlog.ps1` (new items get created; existing ones are skipped —
   edits to already-created issues are made on GitHub directly).
4. Refresh [backlog.md](backlog.md) in this folder so the human-readable mirror stays true.

## Labels

Five dimensions, 23 labels:

| Dimension | Labels |
|-----------|--------|
| Priority | `P0 Critical` (drop other work — money, data loss, release blocker), `P1 High` (needed for the milestone), `P2 Medium` (real work, not urgent), `P3 Low` (nice to have) |
| Type | `feature`, `enhancement`, `bug`, `refactor`, `testing`, `documentation`, `task` |
| Area | `area:grid-core` (deploys via `grid-core/deploy_grid.ps1`), `area:ingest` (deploys via `scripts/deploy_ingest_jobs.ps1`), `area:ops-scripts` (scripts/ and repo policy, deploys nothing), `area:docs` |
| Epic | `epic:greenlight-hardening`, `epic:actual-side`, `epic:inputs-checklist`, `epic:rollout`, `epic:adjacent-debt` |
| Status | `blocked` (blocker named in the issue), `needs-decision` (waiting on a product/commercial call), `good-first-issue` (small, well-bounded, low blast radius) |

## Milestones

| ID | Milestone | Due | Issues |
|----|-----------|-----|--------|
| M1 | Greenlight Hardening | 2026-08-11 | 10 |
| M2 | Actual Side — Pacing vs API Data | 2026-08-25 | 8 |
| M3 | Inputs and Checklist | 2026-09-08 | 6 |
| M4 | Rollout and Docs | 2026-09-22 | 4 |

M1's date matches the meeting's "build this week"; overwrite with real sprint boundaries.

## The board

Five columns. Two automations are native to Projects v2; two need a small GitHub Action.

| # | Column | Means | Entry criteria | Automation |
|---|--------|-------|----------------|------------|
| 1 | Backlog | Accepted, not scheduled. | Issue created, labelled, milestoned. | Auto-add workflow (native). |
| 2 | Ready | Startable today without questions. | AC written, dependencies clear, owner known. | Manual by design. |
| 3 | In Progress | Actively being worked. | Assignee set, branch created. | Needs a small Action (not native). |
| 4 | In Review | Awaiting a second pair of eyes. | PR open referencing the issue. | Needs a small Action (not native). |
| 5 | Done | Merged, deployed where relevant, AC ticked. | Every AC box ticked with evidence. | Item-closed workflow (native). |

GL-28 enters the board at **In Progress** (it is mid-build on a dev branch); everything else
starts at Backlog.

## Working an issue

- Branch names are suggested per issue (`Suggested branch` in the body), e.g.
  `feat/greenlight-background-run`, `fix/purge-client-raw-material`.
- Dependencies are stated in the body (`Depends on: GL-xx`) — respect them or renegotiate them in
  the issue, don't silently ignore them.
- Done means **every acceptance-criteria box ticked with evidence**, not merged-and-hoping.
