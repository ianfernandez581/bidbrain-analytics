r"""
City Perfume — spend-down / geo-holdout LIFT estimator  (T7; see validation_plan.md)
====================================================================================
Run AFTER a spend-down (or geo-holdout) window closes to turn the planning 7× incremental
online-revenue ROAS into a MEASURED number with a confidence band.

  # real run (export the weekly query in validation_plan.md to weekly.csv first):
  .\.venv\Scripts\python.exe client_cityperfume\analysis\measure_lift.py \
      --csv weekly.csv --test-start 2026-08-03 --test-end 2026-09-13

  # see the mechanics on synthetic data (self-validates it recovers a known ROAS):
  .\.venv\Scripts\python.exe client_cityperfume\analysis\measure_lift.py --demo

Method (deliberately NOT a spend-response regression — that would be circular):
  * Build a COUNTERFACTUAL "what online revenue would have been WITHOUT the cut" from a
    non-spend baseline — prior-year same-weeks × recent YoY factor when available, else a
    pre-period linear-trend projection.
  * incremental_revenue = actual − counterfactual over the test (+ optional decay tail).
  * delta_spend         = actual − counterfactual spend (counterfactual = pre-period mean).
  * incremental_rev_ROAS = sum(incremental_revenue) / sum(delta_spend)   (both negative when
    spend is cut → positive slope). Bootstrap the test weeks for a CI.
First-party online revenue (Website + Marketplaces) is the truth; platform attribution is ignored.
"""
import argparse, csv, datetime as dt, math
import numpy as np

DEFAULT_MARGIN = 0.377   # true online gross margin (v_sales COGS); keep in sync with the dashboard

def _d(s): return dt.date.fromisoformat(str(s)[:10])

def load_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append((_d(r["week"]), float(r["spend"]), float(r["online_revenue"])))
    rows.sort()
    weeks = np.array([w for w, _, _ in rows])
    spend = np.array([s for _, s, _ in rows], float)
    rev   = np.array([v for _, _, v in rows], float)
    return weeks, spend, rev

def synth():
    """74 weeks with a KNOWN incremental ROAS and a simulated 6-week non-brand pause."""
    rng = np.random.default_rng(7)
    n = 74
    start = dt.date(2025, 1, 6)
    weeks = np.array([start + dt.timedelta(weeks=i) for i in range(n)])
    woy = np.array([w.isocalendar().week for w in weeks])
    seasonal = 90_000 + 45_000 * np.sin((woy - 10) / 52 * 2 * math.pi) + (woy >= 47) * 120_000  # Nov/Dec lift
    spend = 9_000 + 1_500 * np.sin((woy - 8) / 52 * 2 * math.pi) + rng.normal(0, 800, n)
    TRUE_ROAS = 6.5
    base = seasonal + rng.normal(0, 18_000, n)        # revenue that happens anyway
    rev = base + TRUE_ROAS * spend                    # + ad-driven increment
    # simulate a 6-week non-brand pause: cut ~75% of spend in weeks 56..61
    cut = slice(56, 62)
    spend_cut = spend.copy(); rev_obs = rev.copy()
    spend_cut[cut] = spend[cut] * 0.25
    rev_obs[cut] = base[cut] + TRUE_ROAS * spend_cut[cut]
    return weeks, spend_cut, rev_obs, weeks[cut][0], weeks[cut][-1], TRUE_ROAS

def counterfactual_rev(weeks, rev, test_mask, pre_mask):
    """Predict no-cut revenue for test weeks. Prior-year same-week × recent YoY factor if we have
    a prior year; else project the pre-period linear trend."""
    woy = np.array([w.isocalendar().week for w in weeks])
    yr  = np.array([w.isocalendar().year for w in weeks])
    cf = np.full(weeks.shape, np.nan)
    have_py = False
    # YoY factor from the most recent matched (this-year vs last-year) non-test weeks
    ratios = []
    for i in np.where(~test_mask)[0]:
        py = np.where((woy == woy[i]) & (yr == yr[i] - 1))[0]
        if py.size and rev[py[0]] > 0:
            ratios.append(rev[i] / rev[py[0]])
    yoy = float(np.median(ratios)) if ratios else None
    for i in np.where(test_mask)[0]:
        py = np.where((woy == woy[i]) & (yr == yr[i] - 1))[0]
        if py.size and yoy:
            cf[i] = rev[py[0]] * yoy; have_py = True
    if not have_py:  # fall back to a pre-period linear trend in week index
        idx = np.arange(len(weeks))
        b = np.polyfit(idx[pre_mask], rev[pre_mask], 1)
        cf[test_mask] = np.polyval(b, idx[test_mask])
    return cf, yoy

def estimate(weeks, spend, rev, test_start, test_end, pre_weeks=13, post_weeks=2, margin=DEFAULT_MARGIN, n_boot=4000):
    test_mask = np.array([(test_start <= w <= test_end) for w in weeks])
    if not test_mask.any():
        raise SystemExit("No weeks in the test window — check --test-start/--test-end vs the data.")
    # decay tail: include up to post_weeks after test_end in the revenue read
    end_idx = np.where(test_mask)[0][-1]
    read_mask = test_mask.copy()
    for j in range(1, post_weeks + 1):
        if end_idx + j < len(weeks): read_mask[end_idx + j] = True
    pre_idx = np.where(weeks < test_start)[0][-pre_weeks:]
    pre_mask = np.zeros(len(weeks), bool); pre_mask[pre_idx] = True
    cf_rev, yoy = counterfactual_rev(weeks, rev, read_mask, pre_mask)
    cf_spend = float(spend[pre_mask].mean())                 # spend had we NOT cut
    d_rev   = rev[read_mask] - cf_rev[read_mask]             # observed − counterfactual (≤0 when cut)
    d_spend = spend[read_mask] - cf_spend                    # ≤0 when cut
    roas = d_rev.sum() / d_spend.sum() if d_spend.sum() != 0 else float("nan")
    # bootstrap the read weeks for a CI
    rng = np.random.default_rng(0); k = read_mask.sum(); boots = []
    for _ in range(n_boot):
        s = rng.integers(0, k, k)
        ds = d_spend[s].sum()
        if ds != 0: boots.append(d_rev[s].sum() / ds)
    lo, hi = np.percentile(boots, [5, 95]) if boots else (float("nan"), float("nan"))
    return dict(roas=roas, lo=lo, hi=hi, margin=margin, yoy=yoy,
                d_rev=d_rev.sum(), d_spend=d_spend.sum(), n_read=int(k),
                cf_spend=cf_spend, test_spend=float(spend[test_mask].mean()))

def report(r, true_roas=None):
    print("=" * 64); print("INCREMENTAL ONLINE-REVENUE ROAS - measured")
    print("=" * 64)
    print(f"  read weeks               : {r['n_read']}  (counterfactual via {'YoYx'+format(r['yoy'],'.2f') if r['yoy'] else 'pre-period trend'})")
    print(f"  spend  : {r['cf_spend']:,.0f}/wk no-cut -> {r['test_spend']:,.0f}/wk during test  (delta total {r['d_spend']:,.0f})")
    print(f"  online revenue delta vs counterfactual : {r['d_rev']:,.0f}")
    print(f"  >> incremental revenue ROAS : {r['roas']:.2f}x   90% CI [{r['lo']:.2f}, {r['hi']:.2f}]")
    mroas = r["roas"] * r["margin"]
    print(f"  >> margin ROAS = {r['roas']:.2f}x x {r['margin']*100:.1f}% = {mroas:.2f}x   (net {mroas-1:.2f}x)")
    if true_roas is not None:
        ok = r["lo"] <= true_roas <= r["hi"]
        print(f"\n  [demo] true ROAS = {true_roas:.2f}x -> {'RECOVERED within CI [OK]' if ok else 'outside CI [FAIL]'}")
    print("\n  Compare to the planning 7x. Re-baseline REV_ROAS_ONLINE per validation_plan.md section 3.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv"); ap.add_argument("--test-start"); ap.add_argument("--test-end")
    ap.add_argument("--pre-weeks", type=int, default=13); ap.add_argument("--post-weeks", type=int, default=2)
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN); ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        weeks, spend, rev, ts, te, true_roas = synth()
        report(estimate(weeks, spend, rev, ts, te, a.pre_weeks, a.post_weeks, a.margin), true_roas)
        return
    if not (a.csv and a.test_start and a.test_end):
        raise SystemExit("Provide --csv, --test-start, --test-end (or --demo). See validation_plan.md §5.")
    weeks, spend, rev = load_csv(a.csv)
    report(estimate(weeks, spend, rev, _d(a.test_start), _d(a.test_end), a.pre_weeks, a.post_weeks, a.margin))

if __name__ == "__main__":
    main()
