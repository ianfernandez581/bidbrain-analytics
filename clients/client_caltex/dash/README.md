# clients/client_caltex/dash/ — the Web App (stage 3: password gate + dashboard)

> A **Cloud Run Service** (`caltex-dash`) that's always on. It shows a login screen, and once
> you're authenticated it serves the dashboard and the data — and nothing otherwise.

**Plain English:** this is the *waiter behind a locked door*. A visitor sees a password box;
enter the right password and the dashboard appears, with the app fetching the data file from
locked storage on your behalf. All the charts and tabs live in one HTML file; the Python file
only decides **who** may see it, not **what** it shows.

**Where this sits:** [`../job/`](../job/README.md) writes `caltex.json` to the private bucket →
**[this app]** authenticates the user and serves it at `/data.json` → `dashboard.html` draws the charts.

## What's in here

| File | What it does |
|---|---|
| [`main.py`](main.py) | The Flask app: login, session, the gated routes, `POST /report` (auth + GCS cache, delegates to `report.py`). **Placeholder fallback:** `/data.json` prefers the bucket's `caltex.json`; until the export job has written one it serves the baked-in `placeholder.json` (flagged `meta.placeholder=true` → the dashboard shows a loud "sample data" banner that clears automatically once real data lands). |
| [`dashboard.html`](dashboard.html) | **The entire dashboard UI** — Overview · Delivery · Creative tabs, the Looker date-range picker, Awareness/Consideration stage chips, search, glow styling, CSV exports, and the headless `?bbslides=1` deck path. Carries the house helpers: `bbApplySpendMult` (channel `ttd`), `bb-sortable` tables, `bbDonutCenter`. |
| [`placeholder.json`](placeholder.json) | The deterministic SAMPLE payload (regenerate: `..\gen_placeholder.py`). Same JSON contract as the real `caltex.json`. |
| [`report.py`](report.py) | **AI report generator** (vendored). Two-stage Claude Opus 4.8 call (web-grounded analyst notes → strict slide JSON), retemplated for **TTD awareness + consideration display**; **delivery + engagement ONLY since 2026-08-18** — the prompts, the numeric brief and the slide-1 `area` enum carry no on-site-outcome metric, matching the dashboard (Vertex Gemini fallback). |
| [`bb_deck.js`](bb_deck.js) | The vendored theme-driven deck builder (canonical copy in `client_mongodb/dash/`). |
| [`platform_sso.py`](platform_sso.py) | Cross-subdomain SSO verifier (trusts the platform's `bb_sso` cookie in addition to the local password). |
| [`enable_report_caltex.ps1`](enable_report_caltex.ps1) | One-time AI-report standup (IAM, secrets, timeout). |
| [`deploy_dash_caltex.ps1`](deploy_dash_caltex.ps1) | Per-stage deploy: rebuild + update the SERVICE (use after editing anything in this folder). |
| [`LIVE_URL.md`](LIVE_URL.md) | Deployment status + the **go-live runbook** (verify Windsor data, backfill, deploy). |

## What the dashboard shows

**The Trade Desk programmatic display — mixed awareness + consideration, QLD+WA.** Caltex red
(`#E4002B`) on the petrol-teal Bidbrain canvas, with the 2026-07 **glow package** (animated
north-star KPI bloom, halo on active chips/tabs, lit pacing bar, card hover bloom;
`prefers-reduced-motion` disables the animation).

- **Filters (sticky bar):** Looker date-range picker · **stage chips** (All / Awareness /
  Consideration) · search (ad group / creative / tactic). Every figure recomputes from the shipped
  fact `rows[]` client-side, so any sub-range is exact.
- **Overview** — north-star KPI band (Impressions · Clicks · Spend; clickable — each toggles its
  hero series), context KPIs (CPM / CPC / tactics live — the video-completion and
  viewability tiles were removed 2026-08-05, neither being measurable on this campaign), the
  delivery hero (spend bars vs impressions/clicks lines, VIEW BY Month/Week/Day + AXIS
  Relative/Absolute), budget pacing + progress-to-goal, cumulative impressions vs target pace,
  the attention funnel (impressions → clicks), spend-by-tactic donut (live centre
  total), performance by stage, markets + creative formats, insight cards, and an honest
  "how to read this" note.
- **Delivery** — performance vs targets by ad group (CPM/CTR/CPC Δ columns), the efficiency map
  (CPM vs CTR bubbles per creative with target lines), weekly CPM trend vs target, engagement
  (clicks + CTR) weekly, video engagement (auto-hides when no video delivered), day-of-week
  (full width), spend by ad group, spend-vs-delivery share, the
  per-creative table (thin-volume guard <5k impressions), and a CTR-decay **wear-out watch**
  (no reach/frequency exists in the TTD feed, so wear-out is read from weekly CTR decline).
- **Creative** — top-10 creatives by spend as branded tiles (TTD reports names/formats, not image
  previews) with per-creative metrics + a detail modal.
- **NO on-site outcome is shown anywhere (client request, 2026-08-18).** Every site-visit surface
  was removed: the north-star KPI tile, the hero trend line, the funnel's third step, the
  post-view/post-click donut and its whole card, the `Site visits` column on the stage /
  ad-group / creative tables, the goal-panel bar, the creative-modal `Actions` figure, the
  `site_visits` + `pv_conv`/`pc_conv` CSV columns and the AI-deck payload fields. This was a
  **client instruction, not a measurement judgement** — do not re-add the metric just because the
  slots are populated. **The data path is untouched** — `sql/01_stg_ttd`
  and `job/main.py` still ship the conversion slots and `rows[]` still carries `pv_conv`/`pc_conv`,
  so reinstating the metric is a UI-only edit (plus `report.py`) once TTD actually returns visits.
  `conversion_touch` remains unused. Applications are still unmeasurable — see the client README.
- **Target provenance is visible (2026-08-18).** `targetDerived()` labels any `DERIVED` target as
  "our estimate, not a plan target" (KPI tile) / "est." (ad-group table) — today that is the A$10
  CPC target, which the signed plan does not contain. HARD plan targets (impressions, CPM, CTR,
  budget) render unlabelled. Label any new DERIVED target the same way.
- **The States card states its own coverage (2026-08-18).** The geo pull is manual, so
  `renderMarkets()` prints the geo feed's last day and, when it trails `meta.date_max`, an explicit
  note naming both dates and the unsplit impressions — a trailing chart must never silently
  contradict the KPIs above it. It compares to `date_max`, not today, so the normal 1-day TTD lag
  is not flagged as a fault.

## Routes (`main.py`)

`GET /` (login → dashboard, `no-store`) · `POST /login` (constant-time check) · `GET /logout` ·
`GET /data.json` (bucket `caltex.json`, else the baked placeholder) · `POST /report` (AI deck
JSON, cached in `gs://…/reports/`) · `GET /healthz`. (`GET /creative-img/<id>` is a vestigial
route from the Meta template — TTD has no creative images; it 404s harmlessly.)

Session cookies are `HttpOnly`, `Secure`, `SameSite=None` (the dash is iframed by
`dashboards.bidbrain.ai`); secrets (`DASH_PASSWORD`, `SESSION_SECRET`) injected by Cloud Run.

## See also

- [`../README.md`](../README.md) — client overview · [`LIVE_URL.md`](LIVE_URL.md) — status + go-live runbook.
