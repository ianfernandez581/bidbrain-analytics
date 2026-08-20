# scripts/ - the team workflow (start_day / park / push / ship / go) + machine setup + shared ingest deploy

> How a multi-dev, multi-agent team works this repo without stepping on each other, plus the
> "get this repo running on a fresh Windows laptop" helpers and the deployer for the shared
> raw-layer ingest jobs. **This page is the single full reference for the team-sync flow** -
> AGENTS.md carries only the summary.

**Agent-agnostic by design:** the `/start`-of-day, `/park`, `/push`, `/ship`, `/go` slash commands
exist only in Claude Code (thin wrappers in `.claude/commands/`). Every command is a plain
PowerShell script here, and **any agent (Kimi, Codex, Cursor, ...) or human gets identical
behavior by running the `.ps1` directly**. The scripts do the deterministic mechanical work and
STOP where judgment is needed (a merge conflict, a gate failure) - at that point any agent
resolves and re-runs with `-Resume`. The header comment in each script is its SOP.

---

## The five commands

| Command | Script | What it does |
|---|---|---|
| start_day | `.\scripts\start_day.ps1` | Morning preflight + team alignment. Verifies gcloud CLI creds AND the ADC *identity* (this box silently flips to the no-access agora login), pins the project, checks Secret Manager + BigQuery reachability, removes the dead `bidbrain` remote if present. Then aligns: **parks** uncommitted WIP (never ships it), pushes committed-but-unpushed main work to your dev branch, runs the full ship, pulls main, and **rebases your parked wip/\* branches onto the fresh main** (loud warning if one conflicts or is older than 7 days). `-SkipGo` = creds-only + parked-age warnings. |
| park | `.\scripts\park.ps1` | Commit + push work-in-progress to `wip/<dev>/<desc>` **WITHOUT shipping it**. Ship/go always skip `wip/*`. Re-running appends to the same branch. You end up ON the wip branch, clean tree, work durably on origin. `-Desc feature-name` for a named park; default `wip/<dev>/work`. |
| push | `.\scripts\push-branch.ps1` | Commit ALL local work and push it to YOUR `<dev>/<desc>` branch (first time: `-Dev alex` writes gitignored `scripts/.devname`). Secret guard refuses key-looking files. **Run from a `wip/*` branch it PROMOTES the parked work** into the normal flow and deletes the wip branch. |
| ship | `.\scripts\merge-branches.ps1` | Integrate EVERY dev branch (skipping `wip/*`, with a "N parked branch(es) ignored" line) onto a throwaway `integration/merge` off origin/main, run the sanity gate, fast-forward + push main, **auto-deploy every changed service** (path -> deploy-script map: `Resolve-DeployPlan` in the script), prune merged dev branches, pull local main. `-DryRun` previews everything and changes nothing. |
| go | push + ship in one click | The agent runs `push-branch.ps1` then `merge-branches.ps1` and drives the whole conflict/gate loop. Mind that its ship half integrates and deploys EVERY dev branch, not only yours. |

**The conflict / gate loop (the only judgment in the pipeline):** when ship stops on a MERGE
CONFLICT it leaves the conflict IN the working tree (never aborts). Resolve each file
semantically - preserve BOTH developers' intent, never blindly pick a side - then:

    git add -A ; git commit --no-edit
    .\scripts\merge-branches.ps1 -Resume    # KEEPS your resolution and continues

Same for a sanity-gate failure (fix on the integrated tree, commit, `-Resume`). A plain re-run
without `-Resume` rebuilds the integration from scratch and discards your resolution.

**The sanity gate** (no CI suite exists, so this is the land-blocker): leftover conflict markers,
Python that won't `ast.parse`, invalid JSON, and **secret-looking filenames** (`.env` + variants,
`*.p8/.pem/.pub/.key`, `*credentials*.json`, `service-account*.json`, bare `*_key`, ssh ids;
`.example` templates allowed). The same regex guards `push-branch.ps1` and `park.ps1` locally -
the gate re-checks everything that would LAND because a raw `git push` from another machine
bypasses the local guards.

## Parking: the full contract

- `wip/<dev>/<desc>` branches are **never integrated, never deployed, never pruned** by ship -
  parking exists precisely so unfinished work can sit on origin without going in front of clients.
- **Re-park appends**: park again (same or no `-Desc`) and a new commit lands on the same branch.
  Carrying a dirty tree onto an existing park branch goes through a stash; a conflicted pop STOPS
  with the stash intact (`git stash list`, entry `park-carry`) - nothing is ever lost.
- **Promote** when ready: run `/go` (or `push-branch.ps1`) FROM the wip branch. The content is
  pushed to `<dev>/<desc>`, ship integrates + deploys it, and the wip branch (remote + local) is
  deleted. The owner/desc come from the wip branch name, so promoting a branch parked on another
  machine keeps its identity.
- **start_day keeps parked work fresh**: each morning it rebases YOUR `wip/<dev>/*` branches onto
  the just-pulled main and force-with-lease pushes them. If a rebase conflicts it is ABORTED and
  you get a loud red warning with the manual command - the branch is left exactly as it was. At
  7+ days parked you get an age warning every morning until you promote or delete it.

## Edge cases - designed behavior

| Situation | What happens |
|---|---|
| Dev forgets start_day, works on stale main | Their committed work still integrates on the next push/ship (ship merges every dev branch onto CURRENT origin/main); a textual overlap becomes a conflict the agent resolves semantically in the `-Resume` loop. start_day's final pull realigns the machine. |
| Two devs edit the same file | Ship stops on the first conflicting branch, conflict left in-tree; the agent merges BOTH intents, commits, `-Resume`. The gate then re-checks the resolved tree before anything lands. |
| Uncommitted changes when start_day runs | Auto-**parked** (never shipped, never destroyed). Committed-but-unpushed main commits are treated as finished work and pushed to the dev branch. To ship WIP deliberately, commit it and run `/go` yourself. |
| Ship interrupted mid-run (sleep/crash) | Re-run detects the in-progress merge (`MERGE_HEAD`) and refuses to stomp it: finish the resolution and `-Resume`, or `git merge --abort` and re-run fresh. Everything before landing is local; nothing on origin/production changed yet. |
| Deploy fails for one service mid-plan | main is ALREADY landed (deploys come after). The script reports exactly which deploy failed and prints the remaining deploy scripts to run directly after fixing the cause - re-running ship will NOT redeploy (no diff vs main anymore). |
| Secret accidentally staged | `push-branch`/`park` unstage it and refuse; if one sneaks onto a remote dev branch via raw git, the ship gate FAILS the land with the filename. Never force past the guards; gitignore/move the file (see `bidbrain-vault/`). |
| Dead `bidbrain` remote configured | start_day removes it. `origin` (the ianfernandez581 fork) is the only live remote; all scripts hardcode origin. |
| gcloud silently flipped to the agora account | start_day pins `CLOUDSDK_ACTIVE_CONFIG_NAME=personal` for its own process, then verifies BOTH the CLI account and the ADC identity are `ian@100.digital` (browser reauth if not). Ship independently refuses to deploy when the active account is not a `100.digital` identity. |
| Parked branch rots against moving main | start_day auto-rebases + re-pushes it daily; a conflicted rebase warns loudly with the manual resolution command; 7+ days triggers a nagging age warning. |
| Dev branch already merged but not pruned | Ship's prune step (and `-DeleteMerged` standalone) deletes remote branches fully contained in origin/main - safe by construction, and it never touches `wip/*`. |
| CRLF/LF churn producing phantom diffs | `.gitattributes` normalizes: LF in-repo, `.ps1/.cmd` checked out CRLF, container files (`Dockerfile`, `*.yaml`, `*.sh`) forced LF. If a machine still shows phantom whole-file diffs, run `git add --renormalize .` once and commit; never "fix" it by flipping `core.autocrlf`. |

---

## Machine setup + the rest of scripts/

| File | What it does |
|---|---|
| `setup.ps1` / `setup.cmd` | One-time machine setup: installs Python 3.12 + Cloud SDK (winget), creates `.venv`, installs deps, logs in both credential systems, verifies secret + BigQuery access. Idempotent. |
| `start_day.cmd` | Double-click launcher for `start_day.ps1`. |
| `deploy_ingest_jobs.ps1` | Builds, deploys, and schedules the **8 shared ingest Cloud Run jobs** feeding the `raw_*` datasets: `snowflake-ingest` (self-gating `*/10`), `neto-orders-ingest`, `windsor-meta-ingest`, `windsor-tradedesk-ingest`, `windsor-fields-ingest`, `windsor-reddit-ingest`, `windsor-linkedin-ingest`, `windsor-hubspot-ingest` - the daily ones staggered before the client exports (exact schedules: the `$JOBS` array in the script is the source of truth). All run as `ingest-runner@`; `-Only <name>`, `-SkipBuild`, `-Run`. Ship auto-runs this when anything under `ingest/` changes. |
| `enable_platform_sso.ps1` | Injects `SSO_SECRET`+`CLIENT_KEY` into every client dashboard (all 15). One-time per new dashboard. |
| `enable_super_admin.ps1` | Grants the platform the IAM to rotate every dashboard password. **Add new dashboards to its `$CLIENTS` list** or the super-admin console 403s on them. |
| `enable_google_login.ps1` / `enable_microsoft_login.ps1` | One-time switches for the platform's native Google / Microsoft sign-in (create the OAuth/Entra clients in the Console first). |
| `glm-bypass-mode.ps1` / `.cmd` | Launch Claude Code on Z.ai GLM using the shared `glm-api-key` secret (env vars scoped to the Claude process, restored on exit). Bootstrap the secret once with `create-glm-secret.ps1`. TERMINAL sessions only - the VS Code panel needs `claude-panel-mode.ps1`. |
| `claude-panel-mode.ps1` | Switch the VS CODE PANEL (the Claude extension, which spawns its own process the bypass launchers never reach) between Z.ai GLM and Anthropic by toggling `claudeCode.environmentVariables` in the user settings.json. `status` / `glm` / `claude`; machine-scoped (hits the Agora window too - Agora's twin script toggles the same block for Kimi, last writer wins); reload the window to apply. Twin of Agora's `agora-devtools/claude-panel-mode.ps1`. |
| `_validate_dash_js.py` | Sanity-checks a `dashboard.html`'s inline JS before you deploy it: `.\.venv\Scripts\python.exe scripts\_validate_dash_js.py clients\client_<c>\dash\dashboard.html`. |
| `apply_motion_kit.py` | Applies / re-applies the **BB MOTION KIT** (the shared hover-press-reveal-wash layer) to every client `dash/dashboard.html`. Templates in `motion_kit/`, palette per client in the script's `CLIENTS` dict. `--check` reports, `--revert` strips it out, a client key does one. Skips `cloudflare` (has the richer original) and `sophiie` (own design). **Never hand-edit the injected block** - edit the template and re-run. See AGENTS.md -> "The motion kit". |
| `apply_login_kit.py` | Same, for the **login pages**: every client's `LOGIN_HTML` in `dash/main.py` plus the platform front door and the Extrablack portal (`bidbrain-platform/dash/templates/`). Adds the wash + press/focus vocabulary and three real behaviours (show/hide password, Caps Lock warning, submit-once). |
| `push-branch.ps1` / `merge-branches.ps1` / `park.ps1` / `start_day.ps1` | The team flow above. |

### Why two credential systems are checked
gcloud keeps two independent logins and the org enforces periodic reauth on both: **CLI creds**
(used by `gcloud secrets ...`) and **Application Default Credentials** (used by the Python client
libraries - this is what keeps the committed code portable, no machine paths baked in). Either can
expire - or worse, silently belong to the wrong account - so start_day verifies both *identities*,
not just token existence.

### Notes & gotchas
- These scripts are Windows conveniences; on macOS/Linux `python -m venv` + `pip install -r
  requirements.txt` + `gcloud auth application-default login` are enough (see the root README).
- The `.venv` is a dev-only superset (loaders + one export job's deps); every Cloud Run unit still
  builds its own container from its own `requirements.txt`.
- `Test-Probe` in `setup.ps1`: probe failures are judged by exit code under `Continue`, so an
  expected not-logged-in doesn't kill the script.
- Google Ads + GA4 raw layers refresh via native BigQuery DTS (free, no job here). **Never gate a
  job on the DTS bridge VIEWS** (`raw_google_ads.perf_google_ads`, `raw_ga4.perf_ga4*`) - their
  `last_modified` is frozen; gate on the partitioned `p_ads_*` / `p_ga4_*` base tables.

## See also
- [`AGENTS.md`](../AGENTS.md) - the canonical agent guide (fixed facts, data contract, deploy commands).
- [Root README](../README.md) - the whole-platform human map.
- [`ingest/`](../ingest/) unit READMEs - what each loader pulls and how to run it by hand.
