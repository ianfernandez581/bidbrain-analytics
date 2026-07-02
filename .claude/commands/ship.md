---
description: Integrate every dev branch, resolve any conflicts, land on main, and deploy the changed services — drive the whole loop (1-click).
argument-hint: "[-DryRun] [-NoDeploy] [-Exclude a,b]"
---
You are shipping everyone's work end-to-end by driving `scripts/merge-branches.ps1`. The
developer ran `/ship` and expects ONE click: you handle everything, including deciding how to
resolve conflicts. Loop until it lands (or a genuine blocker needs a human).

1. Run:  `.\scripts\merge-branches.ps1 $ARGUMENTS`

2. If it STOPS on a MERGE CONFLICT — it leaves the conflict IN the working tree (it does not
   abort):
   - Open every conflicted file it listed and resolve each SEMANTICALLY. Preserve BOTH
     developers' intent (e.g. two people who edited the same `dashboard.html`, or both added a
     line to `CLAUDE.md`). NEVER blindly keep one side, and never delete a chunk just to make
     it merge. If a specific hunk is genuinely ambiguous, stop and ask the developer about
     THAT hunk only — not the whole merge.
   - Then:  `git add -A ; git commit --no-edit`
   - Then continue:  `.\scripts\merge-branches.ps1 -Resume`  (this KEEPS your resolution and
     carries on — do NOT re-run without -Resume, that would rebuild from scratch and discard it).
   - Repeat until it no longer stops on a conflict.

3. If it STOPS on the SANITY GATE (leftover conflict marker / Python syntax error / invalid
   JSON — usually a botched resolution): fix the reported file on the integrated tree, then
   `git add -A ; git commit --no-edit` and re-run with `-Resume`.

4. On success it has landed `main` and deployed the changed services. Report to the developer,
   concisely: which services deployed (and their URLs if the deploy scripts printed them), and
   which dev branches were pruned.

Hard rules — do not break these: never bypass or weaken the sanity gate; never land a tree that
fails it; never resolve a conflict by discarding one side's work; never edit a deploy script to
skip a service. Conflict resolution and gate fixes are the ONLY manual judgment calls — the
script does everything else (integrate, gate, land, deploy, prune) for you.

Tip: suggest `-DryRun` first if the developer is unsure what will ship (it previews the land +
deploy plan and changes nothing).
