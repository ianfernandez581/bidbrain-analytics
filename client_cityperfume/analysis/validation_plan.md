# City Perfume — ROAS Validation Plan (T7)

**Goal:** move the **incremental online revenue ROAS** from a *planning estimate* (7×, band 4–9×) to a
**measured** number, so the dashboard's canonical **Margin ROAS (incremental) ≈ 2.6× / 1.6× net** rests
on a real causal test rather than a regression on 17 confounded monthly points. Until then the dashboard
labels 7× as a planning estimate.

> **Status:** designed, not yet executed. Running the test requires changing live ad spend (a forgone-profit
> cost) and/or new geo instrumentation — both need client/ops sign-off. This doc is the design; `measure_lift.py`
> is the estimator to run **after** the test window closes.

---

## 0. What the data says about feasibility (why design matters)

Re-pulled weekly, Jan 2025 – Jun 2026 (n=74 weeks):

| | Mean / week | SD / week | CV |
|---|---|---|---|
| Online revenue (Website + Marketplaces) | A$106,895 | A$45,849 | **0.43** |
| Ad spend (all platforms) | A$9,123 | A$2,775 | 0.30 |

The **CV of 0.43** is the enemy: weekly online revenue swings ±43% from seasonality and promos. At 7× ROAS a
**50% spend cut** (≈A$4.6k/wk) implies a revenue drop of only ≈A$32k/wk — *smaller* than one week's SD
(A$46k). So a shallow cut is undetectable. Two routes follow:

- A **deep** spend-down (≥50%, ideally pause all non-brand) held for **≥4–6 weeks**, read against a modelled
  counterfactual with seasonal controls. Feasible now; moderate power.
- A **geo holdout** (matched control regions) — removes seasonality by design, so far higher power. Needs geo
  instrumentation we don't yet have. **Gold standard; recommended as the definitive test.**

---

## 1. Design A — Spend-down / pulse test (run first; cheapest)

**Hypothesis:** if true incremental ROAS is ~7×, cutting paid spend by ΔS should drop online revenue by
~7·ΔS·(decay) within 1–3 weeks; if the real elasticity is near the seasonality-adjusted M3 signal (~0), online
revenue barely moves.

**Treatment.**
- Cut **all non-brand paid** (Google non-brand PMax/Shopping/Search + Meta prospecting) to ~0 for **N = 4–6 weeks**.
  Keep brand-defence search on (it protects existing demand and would muddy the read).
- Pick a window with **no major promo and no seasonal peak** (avoid Nov–Dec, EOFY, Click Frenzy). A
  Feb–Mar or Aug window is cleanest.
- Pre-register: window dates, which campaigns are cut, expected ΔS, and the decision rule (below) **before** starting.

**Counterfactual.** Predict what online revenue *would* have been with spend unchanged, from:
1. a **pre-period model** (≥13 weeks before the cut): online revenue ~ trend + week-of-year seasonality + spend, and/or
2. **YoY** (same weeks last year, scaled by recent YoY growth) as a cross-check.

**Read.** Incremental revenue = actual − counterfactual over the test (+ a 1–2 wk post-period for decay).
`incremental_rev_ROAS = −Δrevenue / Δspend` (spend fell, so revenue should fall; the ratio is the slope).
Run it through `measure_lift.py` for the point estimate + bootstrap CI.

**Power (rough).** Cumulative expected drop over 4 wks at 7× with a full non-brand pause (≈A$7k/wk cut) ≈
A$196k; counterfactual noise ≈ SD·√N ≈ A$92k → detectable but not crisp. **6 weeks** materially improves it.
If only a 50% cut is acceptable, extend to **8 weeks**.

**Cost.** The test's price is forgone profit during the cut: at the *planning* 1.6× net, pausing ≈A$7k/wk for
6 wks risks ≈A$67k gross profit if 7× is right; ≈A$0 if it's mostly seasonal (which is the thing we're testing).
Frame to the client as a one-off measurement cost.

---

## 2. Design B — Geo holdout (gold standard; needs instrumentation)

Split AU into **matched treatment vs control** regions (states or metro/DMA); **withhold** ads in control for
4–8 weeks; the difference in online revenue trajectory **is** the causal lift, with seasonality cancelled by the
matched control. Use Google Ads **geo experiments** / Meta **GeoLift**.

**Instrumentation required (not present today):**
- **Geo on spend** — geo-split campaigns (or platform geo-experiment tooling).
- **Geo on first-party sales** — add **shipping state/postcode** to `v_sales` → a geo dimension in `stg_sales`.
  Marketplace orders may lack reliable geo (fulfilled by the marketplace) → likely **Website-only** geo holdout.

Higher power and cleaner causality than Design A, but a few weeks of setup. Recommend after Design A gives a first read.

---

## 3. Decision rule → re-baseline the dashboard

Let `R̂` = measured incremental online-revenue ROAS (point estimate) with 90% CI `[lo, hi]`.

| Outcome | Action |
|---|---|
| `R̂` within 4–9× and CI excludes 0 | Set `REV_ROAS_ONLINE = R̂` in `city_perfume_incrementality.py` **and** `dash/dashboard.html`; drop the "planning estimate" caveat → "measured (geo holdout / spend-down, <date>)". |
| `R̂` materially below 4× (CI near 0) | Lower `REV_ROAS_ONLINE` to `R̂`; margin ROAS may fall below 1× net → flag paid efficiency for review. |
| `R̂` above 9× | Raise toward `R̂` (cap at the CI); re-check for leakage (brand cannibalisation, promo overlap). |
| CI too wide (underpowered) | Extend the window or move to Design B; keep 7× flagged as a planning estimate. |

`margin_ROAS = R̂ × online_margin` (online_margin recomputed live from `v_sales`); update the single
`REV_ROAS_ONLINE` constant and redeploy the dash — every tile/chart follows automatically.

---

## 4. Cadence

- **Now:** pre-register + run Design A in the next clean (non-promo) window.
- **After ≥18 months of weekly data:** rebuild as a small **MMM** (adstock + saturation, promo/holiday covariates) — see handoff §7.
- **Re-validate** the constant at least every 2 quarters or after any major channel-mix shift.

---

## 5. Measuring it — `measure_lift.py`

Self-contained estimator (numpy/scipy). Build the weekly series from BigQuery:

```sql
WITH sa AS (
  SELECT DATE_TRUNC(order_date, WEEK(MONDAY)) AS week,
         SUM(IF(channel_group IN ('Website','Marketplace'), line_total, 0)) AS online_revenue
  FROM `bidbrain-analytics.client_cityperfume.stg_sales` GROUP BY week),
ad AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week, SUM(spend_aud) AS spend
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery` GROUP BY week)
SELECT week, spend, online_revenue FROM sa JOIN ad USING (week) ORDER BY week
```

```powershell
# export the query above to weekly.csv, then:
.\.venv\Scripts\python.exe client_cityperfume\analysis\measure_lift.py --csv weekly.csv --test-start 2026-08-03 --test-end 2026-09-13
# or see the mechanics on synthetic data:
.\.venv\Scripts\python.exe client_cityperfume\analysis\measure_lift.py --demo
```

It fits a pre-period counterfactual (revenue ~ trend + spend + week-of-year seasonality), predicts test-period
revenue at the *no-cut* spend, and reports the implied **incremental revenue ROAS** with a bootstrap CI plus the
resulting **margin / net ROAS** at the current online margin.
