# DISCOVERY.md — Phase 0 findings (Transmission Feedback Loop v0)

Date: 2026-08-08 · Branch: `charles/transmission-feedback-v0` · Status: **awaiting confirmation before any build**

The workspace **does** contain the portal shown in the reference screenshot. No stop condition hit.

---

## 1. Stack

- **Flask + Jinja2 templates, vanilla inline JS.** No JS framework, no build step, no bundler.
- Entry point: `bidbrain-platform/dash/main.py` (Flask app; Cloud Run service `platform-dash`, served at dashboards.bidbrain.ai).
- The exact page in the reference screenshot is route **`GET /`** — `home()` at `bidbrain-platform/dash/main.py:261-288`. The `kind == "agency"` branch (`main.py:270-282`) renders **`bidbrain-platform/dash/templates/portal.html`** with `agency={name:"Transmission", slug:"transmission"}`, the client tiles, and the agency logo.
- The tab row (Overview · Data Accuracy · The Grid · The Brain) is `portal.html:358-363`; its CSS and the Data Accuracy pane come from the shared include **`templates/_status_merge.html`** (included at `portal.html:423`). A production "Feedback Loop" tab would be one more `.bbtab`/`.bbpane` pair there — which is why matching `.bbtab` styling matters now.
- The "TRANSMISSION." wordmark is **not text** in the portal — it is an SVG logo file, `bidbrain-platform/dash/agency_transmission.svg`, loaded via `AGENCY_LOGOS` (`main.py:147`) and rendered at `portal.html:356`. White glyphs + magenta full stop **`#e60b7f`**.

## 2. Styling — where it lives and the exact tokens

There are **no external CSS files**. Every template carries its own `<style>` block, in two token layers:

**Layer A — host `:root` (`portal.html:14-18`):**

| Token | Value |
|---|---|
| `--bg` | `#0a0e16` |
| `--panel` (card surface) | `#101726` |
| `--panel-2` | `#0d1420` |
| `--border` | `rgba(255,255,255,.08)` |
| `--text` | `#e8ebf2` |
| `--muted` | `#8a93a6` |
| `--accent` (link blue) | `#3b82f6` |
| `--active` (green) | `#22c55e` |
| `--chip-bg` / `--chip-text` | `#1a2334` / `#9aa6bd` |

**Layer B — the `.bb*` components (`_status_merge.html`, deliberately its own palette per its header comment, lines 2-4):**

- Tab rail: inactive `#8A97AD`, hover/active text `#E8EDF6`, active underline `#34D399`, rail hairline `rgba(255,255,255,.10)` (`_status_merge.html:5-9`).
- **Green primary button** (`#bbsyncall`, the "Sync all dashboards now" the spec names): bg/border `#34D399`, text `#06210f`, radius 10px, font-weight 800, glow `box-shadow:0 2px 12px rgba(52,211,153,.30)`; hover bg `#4ee0aa` + `0 5px 18px rgba(52,211,153,.42)`; `:focus-visible` outline `#A7F3D0` (`_status_merge.html:16-22`).
- Status cards: `#141C2E`, border `rgba(255,255,255,.08)`, radius 13px (`_status_merge.html:56`).
- Health colors: ok `#34D399` · warn `#FBBF24` · bad `#F87171` · na `#94a3b8` (`_status_merge.html:42-45`).
- Amber pill pattern (`.viewpill`/`.wippill`): text `#fbbf24`, bg `rgba(251,191,36,.14)`, border `rgba(251,191,36,.32)`, radius 999px (`portal.html:38-40, 317-319`).
- Grid-pane scoped palette (another self-scoped set): `--p-green:#3dd68c --p-amber:#f5b731 --p-red:#f06e6e` (`portal.html:155-158`).

**Fonts:** the portal loads **Inter from Google Fonts** (`portal.html:10-12`) with fallback `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif`. Mono chips use `ui-monospace,SFMono-Regular,Menlo,monospace` (`portal.html:49`).

**Ambient glow:** the portal background is **cornflower blue**, not teal — `radial-gradient(840px 480px at 50% -6%, rgba(76,141,255,.18), transparent 62%)` + a second blue radial (`portal.html:21-26`). Green appears in a decorative cursor-follow glow `rgba(61,220,132,.10)` (`portal.html:328-346`). See Risk R2.

### Token mapping the build will use (repo value wins over the reference file)

| Prototype role | Reference file has | **Repo value to use** | Source |
|---|---|---|---|
| Page bg | `#0a0f16` | `#0a0e16` | portal.html:15 |
| Card surface | `#0f1622` | `#101726` | portal.html:15 |
| Border | `#1d2837` | `rgba(255,255,255,.08)` | portal.html:15 |
| Body text / secondary / muted | `#e7edf5`/`#93a1b4`/`#5f6f83` | `#e8ebf2` / `#8a93a6` / `#8A97AD` (tab-muted) | portal.html:16, _status_merge:6 |
| Link blue | `#6aa5f8` | `#3b82f6` | portal.html:16 |
| Green (button, active tab, positive) | `#2fd985`/`#3ddc8f` | `#34D399` (+ hover `#4ee0aa`, btn text `#06210f`) | _status_merge:16-20 |
| Red (inaccuracy, needs-improvement rail) | `#f8717a` | `#F87171` | _status_merge:44 |
| Amber (incident, sample pill, warnings) | `#f5b95a` | `#FBBF24` | _status_merge:43 |
| Magenta dot | `#ff2e88` | `#e60b7f` | agency_transmission.svg |
| Mono | (same) | `ui-monospace,SFMono-Regular,Menlo,monospace` | portal.html:49 |
| Sans | system stack | portal's **fallback** stack (Inter itself is a webfont — R1) | portal.html:27 |

Layout, hierarchy, and interaction come from the approved reference (`transmission-feedback-v0-preview (1).html`); only token *values* change per the table.

## 3. Conventions

- `CLAUDE.md` is a one-line pointer to **`md/AGENTS.md`** (canonical agent guide). Rules that bind this build: never commit secrets; never make data JSON public (n/a — file is hand-delivered, README will say DM-only); dashboard JS sanity gate `scripts/_validate_dash_js.py` exists (parser predates ES2021 — no numeric separators); em-dash rule (see R5).
- **Branching:** dev branches are `<dev>/<desc>` (existing: `charles/*`), created/pushed by `scripts/push-branch.ps1`; `wip/*` branches are parked and skipped by ship. **`/ship` integrates every pushed non-wip dev branch onto main and auto-deploys changed services** (`scripts/merge-branches.ps1`, `Resolve-DeployPlan`). See R4.
- **`prototypes/` does not exist yet** and no committed experiments dir exists. The repo's existing home for design previews is **`staging/` — which is gitignored and documented "never commit"** (`.gitignore:51-53`). The prompt explicitly wants a committed `prototypes/` folder on a branch, so prompt wins — flagged as R3 for a human call.
- `.gitignore` will not swallow anything here: only `clients/*/data/*`, `staging/`, key patterns etc. are ignored, so `sample_data.json` and the rest of the folder track normally.
- Lint/format: none configured for HTML/JS beyond `_validate_dash_js.py`; Python has no enforced formatter. Windows PowerShell 5.1 + repo venv for any script runs.

## 4. Reuse (visual patterns to mirror — nothing is importable, the file must be self-contained)

- **Tab rail** `.bbtabs`/`.bbtab` — flex, 2.5px transparent bottom border, active = `#34D399` underline (`_status_merge.html:5-9`). The reference's centered tab row differs slightly from the portal's left-aligned rail; reference wins on layout (it's the approved design).
- **Green primary button** `#bbsyncall` (`_status_merge.html:16-25`) — the exact model for "＋ Log feedback", already glow-styled.
- **Pills/chips:** `.pill.active` green pill (`portal.html:60-62`), amber `.viewpill` (`portal.html:38-40`), mono `.path` chip (`portal.html:65-66`) — models for sample pill, period chip, source chips.
- **Cards:** `.tile` (`portal.html:53-56`, hover = accent border + translateY(-2px)) and `.bbcard` (`_status_merge.html:56`) — report-card model.
- **Status badges** `.status-badge.on-pace/behind/over-pace` tinted-bg pattern (`portal.html:228-234`) — model for type badges.
- **`esc()` helper:** portal JS already uses the identical single-escape-function pattern (`portal.html:501-502`) — same approach as the spec requires.
- Sticky translucent toolbar with `backdrop-filter:blur()` is portal-idiomatic (feedback admin header, `main.py:626-627`).

## 5. Risks / conflicts (human decides; none resolved silently)

- **R1 — Fonts.** The portal's real face is Inter via Google Fonts (`portal.html:10-12`); the prototype is zero-network, so it uses the portal's *fallback* system stack and will not pixel-match portal typography. The prompt already mandates system fonts — accepted, but the prototype will look slightly different from the live portal.
- **R2 — Ambient glow color.** The prompt says "echoes the portal's existing ambient teal radial," but the portal's ambient is **blue** (`rgba(76,141,255,.18)`, `portal.html:22-25`); teal/green exists only in the cursor-follow glow and accents. The prompt and the approved reference agree with each other (teal) and disagree with the live portal. **Recommendation: keep teal** (explicit prompt spec + approved reference Calvin will compare against); switch to portal blue only if portal parity is ruled more important.
- **R3 — Committed prototype vs `staging/` convention.** Repo convention keeps design previews in gitignored `staging/`; the prompt demands a committed `prototypes/` folder on a branch. Proceeding per the prompt.
- **R4 — /ship integration.** Any *pushed* non-wip branch gets landed on main by whoever next runs `/ship`. Until Calvin signs off, this branch stays **local-only** (or parked as `wip/…` if it must be pushed). `prototypes/` should map to no deploy script in `Resolve-DeployPlan` (doc-only changes deploy nothing) — verify before ever shipping.
- **R5 — Em-dashes and mandated .md files.** AGENTS.md bans em-dashes in client-facing copy and narrative .md files about one's own work. This tool is internal-only (never client-facing) and the spec's UI copy contains em-dashes ("Filtered — clear all", tooltip text) — kept verbatim per the prompt. DISCOVERY/QA_NOTES/README are spec-mandated deliverables, not narrative logs — created per the prompt.
- **R6 — Token drift in the reference.** The approved reference's token values differ slightly from the portal's real CSS (table in §2). Per the prompt's "first preference: exact repo tokens," the build will keep the reference's layout but swap in repo values — the result will be *very slightly* different in color from the preview file Calvin saw.

**Next step:** waiting for confirmation (and calls on R2/R6 if the recommendations don't stand) before writing `index.html`, `sheet_to_json.py`, `sample_data.json`, `QA_NOTES.md`, `README.md`.
