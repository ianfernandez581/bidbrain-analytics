---
description: Commit all my local work and push it to my own dev branch (1-click).
argument-hint: "[-Dev name] [-Desc short-description]"
---
Run this repo's push helper and report the result:

    .\scripts\push-branch.ps1 $ARGUMENTS

- On success, tell me the branch name it pushed (e.g. `alex/work`) in one line.
- If it refuses because a file looks like a secret, tell me which file and STOP — do not
  try to force it past the guard. I'll gitignore or move the file, then we retry.

Nothing else — this just gets my work onto my own branch so it can be integrated with /ship.
