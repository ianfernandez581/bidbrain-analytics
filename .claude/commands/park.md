---
description: Commit + push my work-in-progress to a parked branch (wip/<dev>/...) that ship/go will NOT integrate or deploy (1-click).
argument-hint: "[-Dev name] [-Desc short-description] [-Message msg]"
---
Run this repo's park helper and report the result:

    .\scripts\park.ps1 $ARGUMENTS

- On success, tell me in one line: the parked branch name (e.g. `wip/alex/work`) and that
  /ship and /go will ignore it until it is promoted.
- If it refuses because a file looks like a secret, tell me which file and STOP -- do not
  try to force it past the guard. I'll gitignore or move the file, then we retry.
- If it stops on a stash-pop conflict (carrying my changes onto an existing parked branch),
  tell me nothing was lost (the changes are in `git stash list` as `park-carry`, the parked
  commits are intact), help me resolve the conflicts left in the tree, then re-run park.

How parking fits the flow (say this only if I ask):
- Re-running park APPENDS a new commit to the same wip branch.
- `start_day` rebases my parked branches onto the fresh main each morning and warns when
  one has been parked more than 7 days.
- To ship parked work: run /go (or `.\scripts\push-branch.ps1`) FROM the wip branch --
  push-branch detects it, promotes the content to my normal dev branch, and deletes the
  wip branch; /ship then integrates + deploys it.

Nothing else -- this just gets unfinished work safely off my machine WITHOUT shipping it.
