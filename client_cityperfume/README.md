# client_cityperfume/ — City Perfume (AU e-commerce perfume/beauty) · **LIVE**

A self-hosted, password-gated marketing dashboard for **City Perfume**, built on the same
three-stage pattern as every other client (shared raw layers → per-client BigQuery views →
Cloud Run export job writes `cityperfume.json` to a private bucket → password-gated Cloud Run
web app serves it). It pairs the **STT backend + auth model** with an **e-commerce front-end**
(modelled on the Adriatic sample) plus a first-party **Sales** tab neither of them had.

Status: **LIVE** at https://cityperfume-dash-p32gk2wuia-ts.a.run.app (password-gated) — deployed +
verified 2026-06-06: 25 views applied, the export job ran (PII-free `cityperfume.json` in the private
bucket), the dashboard serves all 5 tabs, and the auth flow is confirmed (401 unauth → 200 authed).
Refreshes within ~10 min of new upstream data (self-gating `*/10` scheduler). Both logos (100% Digital + City Perfume) are embedded in the topbar + login.

## The story it tells

City Perfume is e-commerce, so the outcome is **revenue / orders / margin / ROAS**, not sessions —
and the headline is **"ads → actual sales."** The **first-party order ledger** (`v_sales`) is the
single source of truth for revenue, margin, orders, AOV and customers. The three ad platforms
(Google, Meta, Trade Desk) and GA4 each *claim* their own attributed revenue, and they disagree
wildly (Google ~22%, Meta ~4%, GA4 ~2% of true sales over the 12-mo window), so we never sum them.
Instead the headline is a **blended marketing-efficiency ratio**:

- **Blended ROAS = total sales ÷ total ad spend** (≈ **31×**) — no per-platform attribution assumed.
- **Online ROAS = online sales (excl. in-store POS) ÷ total ad spend** (≈ **11.6×**) — the stricter,
  ad-attributable lens (in-store POS is ~63% of revenue; ads influence it only via the omnichannel halo).
- Each platform's own `conversions_value` / `purchase_value` is shown **only as "platform-claimed."**

Everything is **AUD** across all six sources — **no FX**. Reporting window is rolling from
**2025-06-01** (the first full month Meta data exists) to latest.

## The 5 dashboard tabs (`dash/dashboard.html`)

1. **Overview** — KPIs (spend · revenue · blended ROAS · AOV · margin % · repeat-rate · sessions),
   AI commentary, monthly spend-by-platform vs revenue vs ROAS hero, revenue-by-channel donut,
   online-vs-in-store split, spend share. A **Revenue basis** toggle flips All-sales ⇄ Online-only.
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
5. **Ads → Revenue** — spend→sales funnel, weekly spend vs revenue, weekly correlation scatter
   (Pearson r), monthly blended-vs-online ROAS, and a stat strip (blended/online ROAS, cost/order,
   platform-claimed as % of true sales).

**Filters:** **Platform** (Google · Meta · Trade Desk) and **Campaign** (searchable multi-select,
grouped by platform, sorted by spend) rescale the **ad side** client-side; the sales side has no
campaign dimension and stays whole. A **Revenue basis** toggle (All / Online) drives the ROAS framing.
No Country filter (no geo dimension). Sales-channel detail is shown on the Sales tab rather than as a
global filter (the channel decomposition isn't carried on every trend, so a global filter would only
partially rescale — the All/Online toggle covers the meaningful case consistently).

## How it works (3 stages — same shape as every client)

1. **`sql/`** — 25 `CREATE OR REPLACE VIEW`s, `NN_` ordered (06 stg filters → 10–35 rollups).
   Apply with `python client_cityperfume/create_views.py` (or `sql/deploy_views_cityperfume.ps1`).
   The filter strings + the 2025-06-01 window live once in the `01–06 stg_*` views.
2. **`job/`** — `cityperfume-export` Cloud Run job reads the rollup views and writes
   `cityperfume.json` to the private bucket. **Aggregates only** — it never reads `v_sales`/`stg_sales`
   directly and a `assert_no_pii` guard refuses to write if `customer_id`/`email` ever appear.
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

AUD-only (no FX) · window 2025-06-01→latest · v_sales = truth, blended-MER ROAS, platform-claimed
shown separately · Meta includes all `effective_status` (paused/archived hold ~50% of spend) ·
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
- `sql/` — 01–06 staging, 10–12 headline/trend, 13–16 GA4, 20–25 sales, 30–35 campaign/platform.
- `job/` — `main.py` (export), Dockerfile, requirements, cloudbuild, `deploy_job_cityperfume.ps1`.
- `dash/` — `main.py` (auth gate), `dashboard.html`, Dockerfile, requirements, cloudbuild,
  `deploy_dash_cityperfume.ps1`, `LIVE_URL.md`.
- `deploy_cityperfume.ps1` (one-shot) · `scheduler.ps1` · `BUILD_CHECKLIST.md`.

## See also

- Root `README.md` — the full platform map, security model, add-a-client playbook.
- `client_STT/` — the backend + auth template this client mirrors.
