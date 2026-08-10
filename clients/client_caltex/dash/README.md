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
| [`report.py`](report.py) | **AI report generator** (vendored). Two-stage Claude Opus 4.8 call (web-grounded analyst notes → strict slide JSON), retemplated for **TTD awareness + consideration display** (honest "TTD pixel-attributed site action" labelling; Vertex Gemini fallback). |
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
- **Overview** — north-star KPI band (Impressions · Clicks · Site actions · Spend; clickable —
  each toggles its hero series), context KPIs (CPM / CPC / tactics live — the video-completion and
  viewability tiles were removed 2026-08-05, neither being measurable on this campaign), the
  delivery hero (spend bars vs impressions/clicks/actions lines, VIEW BY Month/Week/Day + AXIS
  Relative/Absolute), budget pacing + progress-to-goal, cumulative impressions vs target pace,
  the attention funnel (impressions → clicks → site actions), spend-by-tactic donut (live centre
  total), performance by stage, markets + creative formats, insight cards, and an honest
  "how to read this" note.
- **Delivery** — performance vs targets by ad group (CPM/CTR/CPC Δ columns), the efficiency map
  (CPM vs CTR bubbles per creative with target lines), weekly CPM trend vs target, engagement
  (clicks + CTR) weekly, video engagement (auto-hides when no video delivered), day-of-week,
  post-view vs post-click actions donut, spend by ad group, spend-vs-delivery share, the
  per-creative table (thin-volume guard <5k impressions), and a CTR-decay **wear-out watch**
  (no reach/frequency exists in the TTD feed, so wear-out is read from weekly CTR decline).
- **Creative** — top-10 creatives by spend as branded tiles (TTD reports names/formats, not image
  previews) with per-creative metrics + a detail modal.
- **Site visits honesty:** post-view + post-click TTD attribution only, never framed as sales;
  `conversion_touch` is never used. The attached tracker is the URL-scoped `Landing Page Visit` tag
  (live 2026-08-10), so the KPI means **Star Card landing-page visits**, not all site traffic and
  not applications. When nothing is attributed in range the UI says so instead of showing 0s.

## Routes (`main.py`)

`GET /` (login → dashboard, `no-store`) · `POST /login` (constant-time check) · `GET /logout` ·
`GET /data.json` (bucket `caltex.json`, else the baked placeholder) · `POST /report` (AI deck
JSON, cached in `gs://…/reports/`) · `GET /healthz`. (`GET /creative-img/<id>` is a vestigial
route from the Meta template — TTD has no creative images; it 404s harmlessly.)

Session cookies are `HttpOnly`, `Secure`, `SameSite=None` (the dash is iframed by
`dashboards.bidbrain.ai`); secrets (`DASH_PASSWORD`, `SESSION_SECRET`) injected by Cloud Run.

## See also

- [`../README.md`](../README.md) — client overview · [`LIVE_URL.md`](LIVE_URL.md) — status + go-live runbook.
