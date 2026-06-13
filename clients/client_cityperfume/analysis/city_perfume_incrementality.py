r"""
City Perfume - Advertising Incrementality & Margin-ROAS
=======================================================
Self-contained reproduction of the analysis behind the canonical dashboard ROAS.
Run:  .\.venv\Scripts\python.exe client_cityperfume\analysis\city_perfume_incrementality.py
      (needs numpy, scipy, matplotlib -> analysis/requirements.txt)

Source of truth = first-party sales (Neto / v_sales). Platform-claimed conversion
values (Google/Meta) are deliberately NOT used.

--------------------------------------------------------------------------------
RE-PULL CONFIRMATION (2026-06-12, ian@100.digital, project bidbrain-analytics)
--------------------------------------------------------------------------------
The monthly WHOLE / ONLINE / SPEND arrays below were re-pulled directly from
BigQuery (NOT the in-browser Chart.js scrape) and matched the original handoff
series to the cent. The authoritative queries:

  -- Monthly sales (whole-store, online, in-store) from the first-party ledger:
  SELECT FORMAT_DATE('%Y-%m', DATE_TRUNC(order_date, MONTH)) AS month,
         SUM(line_total)                                           AS whole_store,
         SUM(IF(channel_group != 'In-store POS', line_total, 0))   AS online,
         SUM(IF(channel_group  = 'In-store POS', line_total, 0))   AS in_store
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
  GROUP BY month ORDER BY month;

  -- Monthly ad spend (total) from the unified ad-delivery base (AUD, no FX):
  SELECT FORMAT_DATE('%Y-%m', DATE_TRUNC(metric_date, MONTH)) AS month,
         SUM(spend_aud) AS ad_spend
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
  GROUP BY month ORDER BY month;

ONLINE here = the dashboard's `revenue_online` definition (everything except
In-store POS). It folds in a negligible "Other" tail (<= A$747 over 17 months);
the strict Website+Marketplace figure differs by < 0.1% and does not move any fit.

--------------------------------------------------------------------------------
TRUE ONLINE GROSS MARGIN (computed from v_sales COGS, replaces the 45.4% placeholder)
--------------------------------------------------------------------------------
  -- Revenue-weighted gross margin by channel group (whole window):
  SELECT channel_group, SUM(line_total) AS revenue, SUM(margin) AS margin_dollars,
         SAFE_DIVIDE(SUM(margin), SUM(line_total)) AS margin_pct
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
  GROUP BY channel_group;

  In-store POS  50.03%   (EXCLUDED - dashboard is now online-only)
  Website       38.50%   (A$6.37M revenue)
  Marketplace   34.87%   (A$1.71M revenue; OzSale 15.5% / Catch 26.7% / eBay 34.7% drag it down)
  -> Revenue-weighted ONLINE (Website + Marketplace) gross margin = 37.7%

45.4% was the WHOLE-STORE figure; 38.5% was Website-only. The blended online
margin across all online channels is 37.7% -> MARGIN below.
"""
import numpy as np
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ---------------------------------------------------------------------------
# 1. DATA  (monthly, AUD). Re-pulled & confirmed against BigQuery v_sales +
#    platform spend exports (see header). in_store + online = whole_store.
#    Jun-26 is a PARTIAL month (data through ~12 Jun 2026) -> excluded from fits.
# ---------------------------------------------------------------------------
MONTHS = ["Jan 25","Feb 25","Mar 25","Apr 25","May 25","Jun 25","Jul 25","Aug 25",
          "Sep 25","Oct 25","Nov 25","Dec 25","Jan 26","Feb 26","Mar 26","Apr 26",
          "May 26","Jun 26"]
WHOLE = [1025116.08,1060878.03,1045867.71,902437.66,1111518.92,1172157.00,1210023.03,
         1237396.68,1263173.90,1158870.77,1702552.85,2603237.47,1063291.65,972356.26,
         1128109.61,965719.86,1312656.16,568483.94]
ONLINE= [422321.23,378628.74,338223.25,395097.27,381120.02,480288.75,441483.98,437051.67,
         423003.98,405881.56,801404.47,1086880.14,419559.03,275447.02,391488.17,347788.43,
         379043.37,270702.32]
SPEND = [30535.88,26453.38,27639.73,28948.41,40653.80,45901.34,46176.32,42573.18,47885.21,
         30737.95,56399.02,53869.78,42649.96,30263.96,32468.97,32256.35,49084.47,21336.51]

# Parameters (re-confirmed 2026-06-12):
MARGIN = 0.377            # TRUE revenue-weighted ONLINE gross margin (Website 38.5% + Marketplace 34.9%).
                          # Was 0.454 (whole-store placeholder). See header for derivation.
PARTIAL_LAST = True       # drop the in-progress final month from regressions
WPM = 52/12               # weeks per month, for weekly figures

# ---------------------------------------------------------------------------
# 2. HELPERS
# ---------------------------------------------------------------------------
def trim(x):
    return np.array(x[:-1] if PARTIAL_LAST else x, float)

def ols(x, y):
    sl, ic, r, p, se = stats.linregress(x, y)
    return dict(slope=sl, intercept=ic, r=r, r2=r**2, p=p, se=se)

def yoy_diff_slope(rev, spend):
    """Slope through origin of YoY first differences (Jan-May 25 vs 26).
       Removes month-of-year seasonality."""
    r25, r26 = np.array(rev[0:5]), np.array(rev[12:17])
    s25, s26 = np.array(spend[0:5]), np.array(spend[12:17])
    ds, dr = s26 - s25, r26 - r25
    return np.sum(ds*dr) / np.sum(ds*ds), ds, dr

def report(name, R, S):
    print(f"\n=== {name}  (n={len(R)}) ===")
    print(f"  total revenue A${R.sum():,.0f} | total spend A${S.sum():,.0f} "
          f"| naive total/total ROAS {R.sum()/S.sum():.1f}x")
    m1 = ols(S, R)
    print(f"  [M1] OLS all months   slope={m1['slope']:.2f}x  "
          f"intercept(monthly)=A${m1['intercept']:,.0f}  weekly base=A${m1['intercept']/WPM:,.0f}  "
          f"R2={m1['r2']:.2f}  p={m1['p']:.4f}")
    # exclude December seasonal high-leverage point
    keep = [i for i in range(len(R)) if MONTHS[i] != "Dec 25"]
    m2 = ols(S[keep], R[keep])
    print(f"  [M2] OLS excl Dec      slope={m2['slope']:.2f}x  "
          f"intercept(monthly)=A${m2['intercept']:,.0f}  weekly base=A${m2['intercept']/WPM:,.0f}  "
          f"R2={m2['r2']:.2f}  p={m2['p']:.4f}")
    b3, ds, dr = yoy_diff_slope(R.tolist()+[0], S.tolist()+[0]) if len(R)==17 else (np.nan,None,None)
    print(f"  [M3] YoY-diff slope    {b3:.2f}x   (seasonality removed; n=5, noisy)")
    rho = stats.spearmanr(S, R)[0]
    print(f"  Spearman rho = {rho:.2f}")
    return m1, m2, b3

# ---------------------------------------------------------------------------
# 3. RUN
# ---------------------------------------------------------------------------
Rw, Ro, S = trim(WHOLE), trim(ONLINE), trim(SPEND)
print("#"*70)
print("CITY PERFUME - REAL-WORLD (INCREMENTAL) ROAS")
print("#"*70)
report("WHOLE-STORE revenue ~ spend", Rw, S)
report("ONLINE-ONLY revenue ~ spend", Ro, S)

# ---------------------------------------------------------------------------
# 4. CHOSEN PLANNING ASSUMPTIONS  (see handoff doc for rationale)
#    Revenue ROAS is set from M2 (ex-Dec) discounted toward the weak
#    seasonality-adjusted signal. Margin ROAS = revenue ROAS x gross margin.
# ---------------------------------------------------------------------------
REV_ROAS_ONLINE = 7.0
MARGIN_ROAS = REV_ROAS_ONLINE * MARGIN
NET_ROAS    = MARGIN_ROAS - 1.0
print("\n" + "="*70)
print("RECOMMENDED CANONICAL FIGURES (ONLINE)")
print("="*70)
print(f"  Incremental revenue ROAS : {REV_ROAS_ONLINE:.1f}x   (every A$1 spend -> A${REV_ROAS_ONLINE:.0f} online revenue)")
print(f"  Gross margin (true online): {MARGIN*100:.1f}%")
print(f"  Margin (profit) ROAS     : {MARGIN_ROAS:.2f}x  (gross profit per A$1 spend)")
print(f"  Net profit ROAS          : {NET_ROAS:.2f}x  (after the ad cost itself)")

# ---------------------------------------------------------------------------
# 5. CHART  (online gross-margin bands)
# ---------------------------------------------------------------------------
m = MONTHS[:-1]; s = S; a = Ro
base_margin = (a - REV_ROAS_ONLINE*s) * MARGIN
breakeven   = base_margin + s
top         = a * MARGIN
x = np.arange(len(m))
fig, ax = plt.subplots(figsize=(12, 6.2), dpi=130)
fig.patch.set_facecolor("#faf9f5"); ax.set_facecolor("#ffffff")
ax.fill_between(x, 0, base_margin, color="#E24B4A", alpha=0.20, label="Base online margin - without ads")
ax.fill_between(x, base_margin, breakeven, color="#97C459", alpha=0.65, label="Ad spend (the investment)")
ax.fill_between(x, breakeven, top, color="#27500A", alpha=0.70, label="Net profit generated by ads")
ax.plot(x, base_margin, color="#A32D2D", lw=1.5)
ax.plot(x, breakeven, color="#4d7a16", lw=1.2)
ax.plot(x, top, color="#1d3b06", lw=2)
ax.set_xticks(x); ax.set_xticklabels(m, rotation=45, ha="right", fontsize=10)
ax.set_ylim(0, 0.46e6)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v/1e3:.0f}k"))
ax.set_ylabel("Online gross margin / month")
ax.set_title(f"City Perfume - profit advertising adds (ONLINE)\n"
             f"{MARGIN*100:.1f}% margin | {REV_ROAS_ONLINE:.0f}x revenue ROAS = {MARGIN_ROAS:.1f}x margin ROAS ({NET_ROAS:.1f}x net)",
             fontsize=13, loc="left", pad=14)
ax.grid(axis="y", color="#e6e4dc", lw=0.8); ax.set_axisbelow(True)
for sp in ["top", "right"]: ax.spines[sp].set_visible(False)
ax.legend(loc="upper left", fontsize=10, frameon=False)
plt.tight_layout()
import os
_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "city_perfume_ad_profit_online.png")
plt.savefig(_out, facecolor=fig.get_facecolor())
print(f"\nChart written: {_out}")
