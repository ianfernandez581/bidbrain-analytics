---
description: Push my work, then integrate every dev branch and deploy the changed services — /push + /ship in one click.
argument-hint: "[-Dev name] [-Desc short-description] [-DryRun] [-NoDeploy] [-Exclude a,b]"
---
You are taking the developer's work from local edits all the way to deployed, end-to-end, in ONE
click: first push their work to their own branch, then integrate + deploy everyone's. This is
`/push` followed by `/ship`. Loop until it lands (or a genuine blocker needs a human).

Note on scope: step 2 integrates and deploys EVERY dev branch, not just this developer's. If the
developer seems unsure what else is in flight, suggest running with `-DryRun` first (it previews the
land + deploy plan and changes nothing), then re-run for real.

STEP 1 — push my work:

1. Run:  `.\scripts\push-branch.ps1 $ARGUMENTS`
   (`-Dev`/`-Desc` apply here; the ship-only flags are ignored by this script.)
2. If it REFUSES because a file looks like a secret, tell me which file and STOP — do not try to
   force it past the guard, and do NOT proceed to ship. I'll gitignore or move the file, then retry.
3. On success, note the branch it pushed (e.g. `alex/work`) — you'll report it at the end.

STEP 2 — integrate + deploy everyone (same loop as /ship):

4. Run:  `.\scripts\merge-branches.ps1 $ARGUMENTS`

5. If it STOPS on a MERGE CONFLICT — it leaves the conflict IN the working tree (it does not abort):
   - Open every conflicted file it listed and resolve each SEMANTICALLY. Preserve BOTH developers'
     intent (e.g. two people who edited the same `dashboard.html`, or both added a line to
     `CLAUDE.md`). NEVER blindly keep one side, and never delete a chunk just to make it merge. If a
     specific hunk is genuinely ambiguous, stop and ask the developer about THAT hunk only — not the
     whole merge.
   - Then:  `git add -A ; git commit --no-edit`
   - Then continue:  `.\scripts\merge-branches.ps1 -Resume`  (this KEEPS your resolution and carries
     on — do NOT re-run without -Resume, that would rebuild from scratch and discard it).
   - Repeat until it no longer stops on a conflict.

6. If it STOPS on the SANITY GATE (leftover conflict marker / Python syntax error / invalid JSON —
   usually a botched resolution): fix the reported file on the integrated tree, then
   `git add -A ; git commit --no-edit` and re-run with `-Resume`.

7. On success it has landed `main` and deployed the changed services. Report to the developer,
   concisely: the branch that was pushed in step 1, which services deployed (and their URLs if the
   deploy scripts printed them), and which dev branches were pruned.

Hard rules — do not break these: never bypass or weaken the sanity gate; never land a tree that fails
it; never resolve a conflict by discarding one side's work; never edit a deploy script to skip a
service; never force a suspected secret past the push guard. Conflict resolution and gate fixes are
the ONLY manual judgment calls — the scripts do everything else (push, integrate, gate, land, deploy,
prune) for you.
