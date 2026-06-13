# City Perfume — Real-World ROAS: Analysis Handoff

**Prepared for:** Data Science
**Purpose:** Reproduce the incremental, margin-adjusted ROAS analysis and adopt it as the single canonical ROAS definition across the marketing dashboard. Includes an implementation task list, including switching the dashboard to an online-only revenue basis.
**Companion file:** `city_perfume_incrementality.py` (self-contained; embedded data, regressions, chart).
**Window:** Jan 2025 – Jun 2026 (June 2026 partial, excluded from fits). Currency AUD.

---

## 0. Reproduction log (DS — 2026-06-12)

> Re-pulled directly from BigQuery (`ian@100.digital`, project `bidbrain-analytics`); **not** the in-browser Chart.js scrape.
>
> - **Monthly WHOLE / ONLINE / SPEND series CONFIRMED to the cent** against `stg_sales` + `stg_ad_delivery`. The original scrape was faithful. `ONLINE` = the dashboard's `revenue_online` (everything except In-store POS); the strict Website+Marketplace figure differs by <0.1% (a ≤A$747 "Other" tail) and moves no fit.
> - **Three regressions re-run and CONFIRMED** (OLS all / OLS ex-Dec / YoY-diff) — see §4, numbers reproduce.
> - **True online gross margin computed from `v_sales` COGS = 37.7%** (revenue-weighted across all online channels), *lower* than both the 45.4% whole-store placeholder and the 38.5% Website-only figure, because marketplaces are thinner (OzSale 15.5%, Catch 26.7%, eBay 34.7%). This is now the adopted `MARGIN`.
>
> | Channel group | Revenue | Gross margin |
> |---|---|---|
> | In-store POS | A$13.43M | 50.0% — **excluded** (dashboard is now online-only) |
> | Website | A$6.37M | 38.5% |
> | Marketplace | A$1.71M | 34.9% |
> | **Online (Website + Marketplace, rev-weighted)** | **A$8.07M** | **37.7%** |
>
> **Updated canonical figures (supersede the 45.4%/3.2× placeholders below):**
> `margin_ROAS = 7.0 × 0.377 = 2.64×` → `net = 1.64×`.

---

## 1. TL;DR

The dashboard's headline ROAS (≈31× blended, ≈11.7× online) are *ratio* figures: total revenue ÷ total spend, plus platform-claimed attribution. They massively overstate the causal effect of advertising because (a) they bank revenue that would have occurred anyway, and (b) they confound seasonality (Christmas drives spend *and* sales) with ad effect.

Replacing them with an **incremental, margin-based** figure:

| Metric | Value | Meaning |
|---|---|---|
| Incremental revenue ROAS (online) | **~7×** | Extra online revenue per A$1 spend (planning estimate) |
| Gross margin (true online) | **37.7%** | Revenue-weighted online COGS margin from `v_sales` (was 45.4% placeholder) |
| **Margin (profit) ROAS** | **2.64×** | Gross profit per A$1 spend |
| **Net profit ROAS** | **1.64×** | Profit after the ad cost itself |

Advertising is profitable, but the true return is ~1/12th of the platform-claimed headline. This document standardises that number.

---

## 2. Principle: what counts as "return"

1. **First-party sales are the source of truth.** Revenue, orders, margin come from `v_sales` (Neto). Platform-claimed `conversions_value` / `purchase_value` are each platform's self-attribution, are double-counted across platforms, and are **never** used as the return.
2. **Return = incremental, not total.** The ROAS that matters is *causal lift*: revenue that would not have happened without the spend. Estimate it from the spend↔revenue relationship over time, not from a ratio of totals.
3. **Return = margin, not revenue.** A dollar of revenue is not a dollar of value. Convert incremental revenue to gross profit using margin (POAS — profit on ad spend).

Canonical definition to adopt:

```
margin_ROAS = incremental_revenue_ROAS × gross_margin
net_ROAS    = margin_ROAS − 1        # after paying for the ads
```

---

## 3. Data

Monthly series, AUD. `in_store + online = whole_store`. Full numbers are embedded in `city_perfume_incrementality.py`; reproduced directly from source (see §0).

| Field | Source table / system |
|---|---|
| `whole_store_revenue`, `online_revenue`, `in_store_revenue`, orders, units, margin | BigQuery `v_sales` → `stg_sales` (first-party order ledger) |
| `ad_spend` (total + per platform) | Google Ads, Meta, The Trade Desk spend exports → `stg_ad_delivery` |
| Sessions / funnel (context only) | GA4 — **note:** tracking degraded from ~Oct 2025; directional only, never revenue truth |

Channel grouping used: **Online** = Website + all Marketplaces (BigW, OzSale, Lasoo, eBay, MyDeal, Catch, Amazon AU, EverydayMarket, Stockland). **In-store** = Neto POS.

---

## 4. Method

For dependent variable *Y* (whole-store revenue, then online revenue) against monthly ad spend *X*, run three models. June 2026 is dropped (partial month). n = 17.

- **M1 — OLS, all months.** `Y = a + bX`. Slope *b* = marginal revenue per ad dollar; intercept *a* = implied baseline revenue at zero spend. **Weakness:** dominated by the December high-leverage point.
- **M2 — OLS excluding December.** Same model, drop the Dec seasonal outlier. More stable slope.
- **M3 — Year-on-year first differences (seasonality removed).** Regress (ΔY) on (ΔX) across matched calendar months 2025→2026 (Jan–May, n=5), slope through origin. This nets out month-of-year seasonality — the cleanest causal read available from this data, though noisy at n=5.

Also report Spearman ρ (monotonic robustness) and the naive total/total ratio for comparison.

### Results (re-confirmed 2026-06-12 — see `analysis/regression_output.txt`)

**Whole-store revenue ~ spend**

| Model | Slope (rev ROAS) | Monthly intercept (baseline) | Fit |
|---|---|---|---|
| Naive total/total | 31.5× | — | — |
| M1 OLS all | 28.2× | A$129k | R²=0.48, p=0.002 |
| M2 OLS ex-Dec | 16.6× | A$513k | R²=0.67, p=0.0001 |
| M3 YoY-diff | **9.1×** | — | seasonality-removed, n=5 |
| Spearman ρ | 0.86 | | |

**Online revenue ~ spend**

| Model | Slope (rev ROAS) | Monthly intercept | Fit |
|---|---|---|---|
| Naive total/total | 11.7× | — | — |
| M1 OLS all | 13.4× | −A$64k (implausible) | R²=0.45, p=0.003 |
| M2 OLS ex-Dec | 8.2× | A$108k | R²=0.45, p=0.004 |
| M3 YoY-diff | **−1.3×** | — | seasonality-removed, n=5 |
| Spearman ρ | 0.71 | | |

**Interpretation.** The relationship is real and positive (ρ high, OLS significant) but largely seasonal. The moment seasonality is removed (M3), the whole-store slope falls to ~9× and the online slope collapses to ~0. The online M1 intercept is *negative*, a red flag that the naive model over-attributes. Bottom line: the defensible incremental revenue ROAS is well below the dashboard headline, with a wide confidence band.

### Chosen planning assumption

- **Online incremental revenue ROAS = 7×.** Sits just under the ex-Dec estimate (8.2×), discounted toward the weak seasonality-adjusted signal, and keeps every month's implied baseline non-negative (the binding month, May-26, has revenue/spend = 7.7×). Treat as a **generous** central estimate; defensible band ≈ 4–9×.
- **Margin ROAS = 7 × 0.377 = 2.64×.** Net of ad cost = **1.64×**. *(was 7 × 0.454 = 3.2× under the placeholder margin.)*

These are planning estimates, **not** proven causal numbers — see §7.

---

## 5. Reproduce

```powershell
.\.venv\Scripts\python.exe -m pip install -r client_cityperfume\analysis\requirements.txt
.\.venv\Scripts\python.exe client_cityperfume\analysis\city_perfume_incrementality.py
```

Outputs the full regression table for whole-store and online, the recommended canonical figures, and `city_perfume_ad_profit_online.png` (the gross-margin band chart: base online margin in red, ad spend in light green, net ad-driven profit in dark green). All parameters (`MARGIN`, `REV_ROAS_ONLINE`, `PARTIAL_LAST`) are at the top of the script.

---

## 6. Margin (RESOLVED 2026-06-12)

The original 45.4% was the **whole-store** figure; 38.5% was Website-only. Computed from `v_sales` COGS, the revenue-weighted **online** gross margin is **37.7%** (Website 38.5% on A$6.37M + Marketplace 34.9% on A$1.71M; thin marketplaces OzSale 15.5% / Catch 26.7% / eBay 34.7% drag the blend below Website). This is now `MARGIN` in the script and the dashboard:

```
margin_ROAS = 7 × 0.377 = 2.64×   →   net 1.64×
```

Margin caveat carried forward: `v_sales` margin is net-as-reported; zero-cost-price lines inflate it and promo lines go negative. The 37.7% is the honest revenue-weighted blend over the full window.

---

## 7. Validation before this is treated as truth

This is an observational estimate from 17 monthly points with heavy seasonal confounding. To move from "planning estimate" to "measured":

1. **Geo holdout** — withhold ads in matched control regions, compare lift. Gold standard.
2. **Spend-down / pulse test** — deliberately cut (or pause) spend for 2–4 weeks and measure the revenue response. Cheapest path to a real elasticity.
3. **Weekly granularity + controls** — rebuild on weekly data with explicit seasonality (month/holiday dummies) and promo-calendar covariates; consider a simple MMM (e.g. adstock + saturation) once ≥18 months of weekly data exist.

See `analysis/validation_plan.md` for the concrete spend-down design (T7).

---

## 8. Dashboard implementation tasks

Adopt one canonical ROAS everywhere, and move to an online-only revenue basis.

- [ ] **T1 — Remove in-store POS revenue (online-only basis).** Drop Neto POS from every revenue figure, chart, and KPI. The dashboard becomes online-only (Website + Marketplaces). Remove the "All sales / Online only" toggle and the "Revenue: online vs in-store" / channel-halo framing, or relabel them as deprecated. Confirm `online_revenue` is the default everywhere.
- [ ] **T2 — Replace all ROAS with margin (profit) ROAS.** Retire blended 31.4×, online 11.8×, and YoY 29.1×. Compute `margin_ROAS = incremental_rev_ROAS × online_margin` from the agreed parameters. Single definition across Overview, Ads→Revenue, and Year-on-Year tabs.
- [ ] **T3 — Relabel the metric.** Rename "ROAS / Blended ROAS" → "Margin ROAS (incremental)" so it is not confused with the old ratio definition. Show net ROAS alongside.
- [ ] **T4 — Drop platform-claimed revenue from headline tiles.** Keep platform-claimed conversions on the Paid Media tab as clearly-labelled context only; never in a ROAS tile.
- [ ] **T5 — Substitute true online margin.** Replace 45.4% with the revenue-weighted online COGS margin = 37.7% (§6).
- [ ] **T6 — Add a methodology footnote.** One line: "ROAS = incremental online revenue (regression-based) × gross margin; platform attribution excluded; see analysis handoff." Link this doc.
- [ ] **T7 — Set up the validation test (§7).** Schedule a spend-down or geo holdout so the 7× / 2.64× can be confirmed or corrected, then re-baseline. See `analysis/validation_plan.md`.

---

## 9. File manifest

| File | Contents |
|---|---|
| `city_perfume_roas_handoff.md` | This document |
| `city_perfume_incrementality.py` | Reproducible analysis + chart generator |
| `city_perfume_ad_profit_online.png` | Online gross-margin band chart |
| `regression_output.txt` | Captured console output of the reproduction run |
| `validation_plan.md` | T7 spend-down / geo-holdout design |

*Reproduced figures may shift once a holdout or spend-down test confirms the 7×. Treat 7× / 2.64× as the working baseline, not a measured constant, until then.*
