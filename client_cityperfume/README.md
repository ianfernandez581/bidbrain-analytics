# client_cityperfume/ — City Perfume (AU e-commerce perfume/beauty) · **LIVE**

A self-hosted, password-gated marketing dashboard for **City Perfume**, built on the same
three-stage pattern as every other client (shared raw layers → per-client BigQuery views →
Cloud Run export job writes `cityperfume.json` to a private bucket → password-gated Cloud Run
web app serves it). It pairs the **STT backend + auth model** with an **e-commerce front-end**
(modelled on the Adriatic sample) plus a first-party **Sales** tab neither of them had.

Status: **LIVE** at https://cityperfume-dash-p32gk2wuia-ts.a.run.app (password-gated) — first
deployed + verified 2026-06-06; since extended (YoY tab, day-grained views, global Sales-channel +
date-range filters). The export job runs (PII-free `cityperfume.json` in the private bucket), the
dashboard serves all 6 tabs, and the auth flow is confirmed (401 unauth → 200 authed). **36 views**
now applied. Refreshes within ~10 min of new upstream data (self-gating `*/10` scheduler). Both logos
(100% Digital + City Perfume) are embedded in the topbar + login.

## The story it tells

City Perfume is e-commerce, so the outcome is **revenue / orders / margin / ROAS**, not sessions —
and the headline is **"ads → actual profit."** The **first-party order ledger** (`v_sales`) is the
single source of truth for revenue, margin, orders, AOV and customers. The three ad platforms
(Google, Meta, Trade Desk) and GA4 each *claim* their own attributed revenue, and they disagree
wildly (Google ~22%, Meta ~4%, GA4 ~2% of true sales), so we never sum them — platform-claimed
figures are **context only**.

The dashboard is **online-only** (Website + Marketplaces; **in-store POS excluded**) and reports a
**single canonical ROAS — the incremental, margin-based return**, NOT a total-revenue ÷ spend ratio:

- **Margin ROAS (incremental) ≈ 2.6×**, **net ≈ 1.6×** (after the ad cost itself).
- = **7× incremental online revenue** per A$1 (regression-based; planning estimate, band 4–9×)
  × **37.7% online gross margin** (revenue-weighted from `v_sales` COGS).
- The old ratio headline (≈31× blended / ≈11.7× online) overstated ad impact ~10× — retired.
- 7× is a **planning estimate**, not a measured constant, **pending a spend-down / geo holdout**.

Full methodology, the reproducible regressions and the validation plan live in
[`analysis/`](analysis/) (`city_perfume_roas_handoff.md`, `city_perfume_incrementality.py`,
`validation_plan.md`). Everything is **AUD** — **no FX**. Window rolls from **2025-01-01** to latest.

## The 6 dashboard tabs (`dash/dashboard.html`)

1. **Overview** — KPIs (spend · online revenue · AOV · margin % · repeat-rate · sessions),
   AI commentary, monthly spend-by-platform vs online-revenue hero, revenue-by-online-channel donut,
   a **Margin ROAS (incremental)** callout, and spend share.
2. **Paid Media** — all platforms (ignores the Platform chips; Campaign filter applies); monthly
   spend + ROAS, spend share, platform comparison table **incl. platform-claimed ROAS**, Google by
   campaign type, Meta creative mix (video/image) + a creative gallery, top-campaigns table.
3. **Website & GA4** — sessions by channel, GA4 revenue by channel, the on-site funnel
   (sessions → view_item → add_to_cart → begin_checkout → purchase), monthly sessions by bucket,
   top source/mediums. Carries a visible **"GA4 tracking degraded from Oct 2025"** data-quality note.
4. **Sales & Products** *(unique)* — first-party truth: revenue/margin/AOV trend, **prominent
   new-vs-returning section** (cards + monthly stacked revenue + returning-share + split donut),
   revenue by channel, category mix (EDP/EDT/Parfum/Gift Set & Hamper/Other), top products by
   revenue **or** margin, sales-by-channel detail.
5. **Ads → Revenue** — spend→sales funnel, weekly spend vs online revenue, weekly correlation scatter
   (Pearson r, flagged as largely seasonal), the **monthly profit band** (base online margin + ad spend
   + net ad-driven profit), and a stat strip (Margin ROAS incremental, net ROAS, cost/order, platform-
   claimed as % of true online sales). Carries the methodology footnote linking the analysis handoff.
6. **Year on Year** — plain-dollar finance view (AUD): each month against the same calendar month a year
   earlier, $ + YoY%, from the `yoy_monthly` view. The in-progress month is compared **month-to-date**
   (same day-count both years) so it stays fair. The Date range acts as a **month filter** and the Sales
   channel chips scope revenue; ad spend stays whole (ad data has no channel split). Prior-year baseline
   is our own first-party `v_sales` (to be reconciled with the client's old tracker).

**Filters (global, in the topbar):**
- **Date range** — a Looker-style picker (presets + custom range). The finest grain is the **DAY**: every
  `*_daily` view is clipped to the selected range, aggregated up for KPIs/donuts/tables, and bucketed to
  day/week/month for trend charts by span. When the range is **not** narrowed, the full-period arrays stay
  the exact source (so the default view is unchanged and distinct-customer counts stay exact). On the
  Year-on-Year tab the range acts as a **month filter**.
- **Platform** (Google · Meta · Trade Desk) and **Campaign** (searchable multi-select, grouped by platform,
  sorted by spend) rescale the **ad side** client-side.
- **Sales channel** chips (Website / Marketplace = the online `channel_group` values) scope the **online**
  revenue side. There is no in-store and no All/Online toggle — the dashboard is online-only. No Country
  filter (no geo dimension).

## How it works (3 stages — same shape as every client)

1. **`sql/`** — 36 `CREATE OR REPLACE VIEW`s, `NN_` ordered (01–06 stg filters → 10–40 full-period
   rollups → 50–59 day-grained rollups). Apply with `python client_cityperfume/create_views.py`
   (or `sql/deploy_views_cityperfume.ps1`). The filter strings + the `2025-01-01` window live once in
   the `01–06 stg_*` views. (See [`sql/README.md`](sql/README.md) for the per-view map.)
2. **`job/`** — `cityperfume-export` Cloud Run job reads the rollup views and writes
   `cityperfume.json` to the private bucket. **Aggregates only** — it never reads `v_sales`/`stg_sales`
   directly and a `assert_no_pii` guard refuses to write if `customer_id`/`email` ever appear. It is
   **self-gating** (`freshness.py`): on each `*/10` UTC scheduler tick it probes the BigQuery
   `__TABLES__.last_modified` of the raw tables it reads (`raw_neto.orders`, `raw_google_ads.perf_google_ads`,
   `raw_windsor.perf_meta` / `perf_the_trade_desk`, `raw_ga4.perf_ga4` / `perf_ga4_events`) against the
   `_freshness.json` watermark in the bucket and rebuilds **only** when one advanced (else exits 0).
   `FORCE_REBUILD=1` bypasses the gate. See [`job/README.md`](job/README.md).
3. **`dash/`** — `cityperfume-dash` Cloud Run service: a Flask password gate that serves
   `dashboard.html` and proxies `cityperfume.json` at `/data.json` to authenticated sessions only.
   Auth logic is byte-for-byte STT; only the login branding + data object differ.

## The data contract (matched by name across three files)

    sql/*.sql view column  →  job/main.py JSON key  →  dashboard.html data.* key

The job uses a generic `clean()` mapper, so JSON keys mirror the view columns exactly. Rename a
column in a view and you must re-run the job; the dashboard reads the same names. **All-campaigns
selection reproduces the whole-window ad totals exactly** (verified: kpi = monthly = weekly =
ad_campaigns = platform_summary = **A$517,729**; sales views all = **A$16,053,034**).

## Deploy / refresh (copy-paste, PowerShell — build & deploy as yourself, never cloudbuild from a laptop)

```powershell
# FIRST-TIME STANDUP (idempotent; prompts for the dashboard password; dataset already exists → preserved):
.\client_cityperfume\deploy_cityperfume.ps1

# edited a sql/*.sql view → reapply views + re-run the job:
.\client_cityperfume\sql\deploy_views_cityperfume.ps1

# edited job/main.py (JSON shape) → rebuild + deploy + run the job:
.\client_cityperfume\job\deploy_job_cityperfume.ps1

# edited dash/dashboard.html or dash/main.py → rebuild + redeploy the service:
.\client_cityperfume\dash\deploy_dash_cityperfume.ps1

# adjust the refresh cadence (the scheduler defaults to */10 UTC, self-gating):
.\client_cityperfume\scheduler.ps1 -Schedule "*/10 * * * *"
```

The service serves `dashboard.html` with `Cache-Control: no-store`, so a redeploy shows immediately,
and it always reads whatever JSON is currently in the bucket.

## EDA decisions (recorded in `BUILD_CHECKLIST.md`)

AUD-only (no FX) · window 2025-01-01→latest · v_sales = truth · ONLINE-ONLY (in-store POS excluded) ·
single canonical incremental Margin ROAS (7× × 37.7% online margin), platform-claimed shown separately ·
Meta includes all `effective_status` (paused/archived hold ~50% of spend) ·
TTD stays upper-funnel (parsed `conversion_touch_03`, no revenue) · concentration category via regex ·
new-vs-returning via first-ever-order over full history. **Flagged to client:** GA4 tracking broke
~Oct 2025; margin has zero-cost-price / negative-promo noise.

## Coordinates

| | |
|---|---|
| GCP project | `bidbrain-analytics` (au-southeast1) |
| Dataset | `client_cityperfume` (pre-existing — holds `v_sales`) |
| Bucket / object | `bidbrain-analytics-cityperfume-dash` / `cityperfume.json` |
| Job / service | `cityperfume-export` / `cityperfume-dash` |
| SAs | `cityperfume-dash-job@…` (job) · `cityperfume-dash-web@…` (web) |
| Secrets | `cityperfume-dash-password` · `cityperfume-dash-session-key` |
| Subdomain (later) | `cityperfume.bidbrain.ai` |

## Files

- `create_views.py` — applies `sql/*.sql` in order.
- `sql/` (36 views) — 01–06 staging, 10–12 headline/trend, 13–16 GA4, 20–25 sales, 30–35
  campaign/platform, 40 year-on-year, 50–59 day-grained (the range-filter source). See
  [`sql/README.md`](sql/README.md).
- `job/` — `main.py` (export), `freshness.py` (self-gating helper), Dockerfile, requirements,
  cloudbuild, `deploy_job_cityperfume.ps1`. See [`job/README.md`](job/README.md).
- `dash/` — `main.py` (auth gate), `dashboard.html`, Dockerfile, requirements, cloudbuild,
  `deploy_dash_cityperfume.ps1`, `LIVE_URL.md`. See [`dash/README.md`](dash/README.md).
- `analysis/` — ROAS analysis handoff, reproducible incrementality script + chart, T7 validation plan.
- `deploy_cityperfume.ps1` (one-shot) · `scheduler.ps1` · `BUILD_CHECKLIST.md`.

## See also

- Root `README.md` — the full platform map, security model, add-a-client playbook.
- `client_STT/` — the backend + auth template this client mirrors.
