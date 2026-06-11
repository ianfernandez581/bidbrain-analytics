r"""validate.py - City Perfume dashboard BigQuery checker / validator.

Prints (1) a single Platform | Metric | Number table of the source-of-truth totals the
dashboard must match, then (2) reconciliation checks (PASS/FAIL) that prove the views are
internally consistent and agree with the raw layers. Reads the same views the export job
(job/main.py) reads, so the numbers below are exactly what cityperfume.json / the live
dashboard should show.

Run:  .\.venv\Scripts\python.exe client_cityperfume\validate.py
(run create_views.py first if the views don't exist yet). Exits non-zero if any check fails.
"""
import sys
from decimal import Decimal
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
DATASET = "client_cityperfume"
WIN = "2025-06-01"                       # window start (matches every stg_* view)
D = f"`{PROJECT}.{DATASET}"              # view prefix; close with .view`

# Build-time reference snapshot (2026-06-06). Live numbers will be >= these as data
# refreshes daily; here only to sanity-check the order of magnitude.
REF = {"ad_spend": 517_729, "revenue_total": 16_053_034, "orders_total": 64_834,
       "sessions": 453_782, "roas_blended": 31.0, "roas_online": 11.6}

bq = bigquery.Client(project=PROJECT, location=LOCATION)


def q(sql):
    return [dict(r) for r in bq.query(sql, location=LOCATION).result()]


def row1(view):
    r = q(f"SELECT * FROM {D}.{view}`")
    return r[0] if r else {}


# ---- formatters -------------------------------------------------------------
def _n(v):
    return float(v) if isinstance(v, Decimal) else v


def money(v, d=0):
    v = _n(v)
    return "-" if v is None else f"A${v:,.{d}f}"


def integer(v):
    v = _n(v)
    return "-" if v is None else f"{round(v):,}"


def roas(v):
    v = _n(v)
    if v is None:
        return "-"
    return f"{v:.1f}x" if abs(v) >= 10 else f"{v:.2f}x"


def pct(v, d=1):
    v = _n(v)
    return "-" if v is None else f"{v * 100:.{d}f}%"


def ratio(v, d=1):
    v = _n(v)
    return "-" if v is None else f"{v:.{d}f}"


def close(a, b, rel=1e-6, floor=0.5):
    a, b = (_n(a) or 0), (_n(b) or 0)
    return abs(a - b) <= max(floor, rel * max(abs(a), abs(b)))


# =============================================================================
def main():
    kpi = row1("kpi")
    sk = row1("sales_kpi")
    fn = row1("ga4_funnel")
    ps = {r["platform"]: r for r in q(f"SELECT * FROM {D}.platform_summary`")}
    ga = q(f"SELECT SUM(engaged_sessions) eng, SUM(transactions) txn FROM {D}.ga4_channels`")[0]
    g, m, t = ps.get("google", {}), ps.get("meta", {}), ps.get("ttd", {})

    plat_claimed = (_n(kpi.get("google_rev_claimed")) or 0) + (_n(kpi.get("meta_rev_claimed")) or 0)
    plat_claimed_share = plat_claimed / _n(kpi["revenue_total"]) if kpi.get("revenue_total") else None

    # ---- (1) the reference table ------------------------------------------
    T = []  # (platform, metric, number)

    def add(p, metric, num):
        T.append((p, metric, num))

    add("Whole store (v_sales)", "Sales revenue", money(sk["revenue_total"]))
    add("Whole store (v_sales)", "Gross margin", money(sk["margin_total"]))
    add("Whole store (v_sales)", "Margin %", pct(sk["margin_pct"]))
    add("Whole store (v_sales)", "Orders", integer(sk["orders_total"]))
    add("Whole store (v_sales)", "AOV", money(sk["aov"], 2))
    add("Whole store (v_sales)", "Units", integer(sk["units"]))
    add("Whole store (v_sales)", "Units / order", ratio(sk["units_per_order"]))
    add("Whole store (v_sales)", "Distinct customers", integer(sk["customers_total"]))
    add("Whole store (v_sales)", "New customers", integer(sk["new_customers"]))
    add("Whole store (v_sales)", "Returning customers", integer(sk["returning_customers"]))
    add("Whole store (v_sales)", "New orders", integer(sk["new_orders"]))
    add("Whole store (v_sales)", "Returning orders", integer(sk["returning_orders"]))
    add("Whole store (v_sales)", "New revenue", money(sk["new_revenue"]))
    add("Whole store (v_sales)", "Returning revenue", money(sk["returning_revenue"]))
    add("Whole store (v_sales)", "Returning revenue share", pct(sk["returning_revenue_share"]))
    add("Whole store (v_sales)", "Repeat-order rate", pct(sk["repeat_order_rate"]))

    add("Sales by channel", "Online (excl. POS)", money(sk["revenue_online"]))
    add("Sales by channel", "Website", money(sk["revenue_website"]))
    add("Sales by channel", "In-store POS", money(sk["revenue_instore"]))
    add("Sales by channel", "Marketplace", money(sk["revenue_marketplace"]))

    add("Google Ads", "Spend", money(g.get("spend_aud")))
    add("Google Ads", "Impressions", integer(g.get("imps")))
    add("Google Ads", "Clicks", integer(g.get("clicks")))
    add("Google Ads", "CTR", pct(g.get("ctr"), 2))
    add("Google Ads", "CPC", money(g.get("cpc"), 2))
    add("Google Ads", "Conversions (claimed)", integer(g.get("platform_conversions")))
    add("Google Ads", "Revenue (claimed)", money(g.get("platform_revenue_claimed")))
    add("Google Ads", "Claimed ROAS", roas(g.get("platform_claimed_roas")))

    add("Meta", "Spend", money(m.get("spend_aud")))
    add("Meta", "Impressions", integer(m.get("imps")))
    add("Meta", "Clicks", integer(m.get("clicks")))
    add("Meta", "CTR", pct(m.get("ctr"), 2))
    add("Meta", "CPC", money(m.get("cpc"), 2))
    add("Meta", "Purchases (claimed)", integer(m.get("platform_conversions")))
    add("Meta", "Purchase value (claimed)", money(m.get("platform_revenue_claimed")))
    add("Meta", "Claimed ROAS", roas(m.get("platform_claimed_roas")))

    add("The Trade Desk", "Spend", money(t.get("spend_aud")))
    add("The Trade Desk", "Impressions", integer(t.get("imps")))
    add("The Trade Desk", "Clicks", integer(t.get("clicks")))
    add("The Trade Desk", "CTR", pct(t.get("ctr"), 2))
    add("The Trade Desk", "View-through conv. (touch_03)", integer(t.get("platform_conversions")))
    add("The Trade Desk", "Revenue (claimed)", "- (none in source)")

    add("All paid media", "Total ad spend", money(kpi["ad_spend"]))
    add("All paid media", "Total impressions", integer(kpi["ad_imps"]))
    add("All paid media", "Total clicks", integer(kpi["ad_clicks"]))
    add("All paid media", "Blended CTR", pct(kpi["ctr"], 2))

    add("GA4 site (degraded Oct'25)", "Sessions", integer(kpi["sessions"]))
    add("GA4 site (degraded Oct'25)", "Paid sessions", integer(kpi["paid_sessions"]))
    add("GA4 site (degraded Oct'25)", "Engaged sessions", integer(ga["eng"]))
    add("GA4 site (degraded Oct'25)", "Transactions", integer(ga["txn"]))
    add("GA4 site (degraded Oct'25)", "Purchase revenue (claimed)", money(kpi["ga4_revenue"]))
    add("GA4 site (degraded Oct'25)", "Ecommerce purchases", integer(kpi["ga4_purchases"]))
    add("GA4 site (degraded Oct'25)", "Conversion rate", pct(kpi["ga4_cvr"], 2))

    add("GA4 funnel (site-wide)", "Sessions", integer(fn["sessions"]))
    add("GA4 funnel (site-wide)", "view_item", integer(fn["view_item"]))
    add("GA4 funnel (site-wide)", "add_to_cart", integer(fn["add_to_cart"]))
    add("GA4 funnel (site-wide)", "begin_checkout", integer(fn["begin_checkout"]))
    add("GA4 funnel (site-wide)", "purchase", integer(fn["purchase"]))

    add("Blended (headline)", "Blended ROAS (all sales)", roas(kpi["roas_blended"]))
    add("Blended (headline)", "Online ROAS (excl. POS)", roas(kpi["roas_online"]))
    add("Blended (headline)", "Cost per order", money(kpi["cost_per_order"], 2))
    add("Blended (headline)", "Google-claimed revenue", money(kpi["google_rev_claimed"]))
    add("Blended (headline)", "Meta-claimed revenue", money(kpi["meta_rev_claimed"]))
    add("Blended (headline)", "Platform-claimed % of true sales", pct(plat_claimed_share))

    # print table
    w0 = max(len(r[0]) for r in T + [("Platform", "", "")])
    w1 = max(len(r[1]) for r in T + [("", "Metric", "")])
    w2 = max(len(r[2]) for r in T + [("", "", "Number")])
    ws = kpi.get("window_start"); we = kpi.get("window_end")
    print(f"\nCity Perfume dashboard - source-of-truth totals  |  window {ws} -> {we}  |  AUD\n")
    print(f"{'Platform':<{w0}}  {'Metric':<{w1}}  {'Number':>{w2}}")
    print(f"{'-' * w0}  {'-' * w1}  {'-' * w2}")
    prev = None
    for p, metric, num in T:
        if prev is not None and p != prev:
            print()
        print(f"{p:<{w0}}  {metric:<{w1}}  {num:>{w2}}")
        prev = p

    # ---- (2) reconciliation checks ----------------------------------------
    r = q(f"""
    SELECT
      (SELECT SUM(spend_aud)            FROM {D}.ad_campaigns`)        AS camp_spend,
      (SELECT SUM(ad_spend)             FROM {D}.monthly`)             AS monthly_spend,
      (SELECT SUM(ad_spend)             FROM {D}.weekly`)              AS weekly_spend,
      (SELECT SUM(spend_aud)            FROM {D}.platform_summary`)    AS platsum_spend,
      (SELECT SUM(spend_aud)            FROM {D}.ad_campaign_monthly`) AS campmonthly_spend,
      (SELECT SUM(spend_aud)            FROM {D}.ad_campaign_weekly`)  AS campweekly_spend,
      (SELECT SUM(revenue_total)        FROM {D}.sales_monthly`)       AS salesmonthly_rev,
      (SELECT SUM(revenue)              FROM {D}.sales_by_channel`)    AS bychannel_rev,
      (SELECT SUM(revenue)              FROM {D}.sales_category`)      AS bycategory_rev,
      (SELECT SUM(new_revenue+returning_revenue) FROM {D}.sales_new_returning`) AS newret_rev,
      (SELECT SUM(new_orders+returning_orders)   FROM {D}.sales_new_returning`) AS newret_orders,
      (SELECT SUM(sessions)             FROM {D}.ga4_channels`)        AS ga4ch_sessions,
      (SELECT SUM(sessions)             FROM {D}.ga4_monthly_channel`) AS ga4mo_sessions,
      (SELECT SUM(spend) FROM `{PROJECT}.raw_google_ads.perf_google_ads`
        WHERE account_name='City Perfume'      AND metric_date >= DATE '{WIN}') AS raw_google,
      (SELECT SUM(cost)  FROM `{PROJECT}.raw_windsor.perf_meta`
        WHERE account_name='Cityperfume.com.au' AND metric_date >= DATE '{WIN}') AS raw_meta,
      (SELECT SUM(cost)  FROM `{PROJECT}.raw_windsor.perf_the_trade_desk`
        WHERE advertiser_name='City Perfume'    AND metric_date >= DATE '{WIN}') AS raw_ttd,
      (SELECT SUM(line_total) FROM `{PROJECT}.{DATASET}.v_sales`
        WHERE DATE(date_placed) >= DATE '{WIN}') AS raw_sales_rev
    """)[0]
    raw_ad = (_n(r["raw_google"]) or 0) + (_n(r["raw_meta"]) or 0) + (_n(r["raw_ttd"]) or 0)

    checks = [
        # ad-spend invariant (campaign-filter rescaling depends on this)
        ("kpi.ad_spend == sum(ad_campaigns)", kpi["ad_spend"], r["camp_spend"]),
        ("kpi.ad_spend == sum(monthly)", kpi["ad_spend"], r["monthly_spend"]),
        ("kpi.ad_spend == sum(weekly)", kpi["ad_spend"], r["weekly_spend"]),
        ("kpi.ad_spend == sum(platform_summary)", kpi["ad_spend"], r["platsum_spend"]),
        ("kpi.ad_spend == sum(ad_campaign_monthly)", kpi["ad_spend"], r["campmonthly_spend"]),
        ("kpi.ad_spend == sum(ad_campaign_weekly)", kpi["ad_spend"], r["campweekly_spend"]),
        # sales-truth invariant
        ("kpi.revenue == sales_kpi.revenue", kpi["revenue_total"], sk["revenue_total"]),
        ("kpi.revenue == sum(sales_monthly)", kpi["revenue_total"], r["salesmonthly_rev"]),
        ("kpi.revenue == sum(sales_by_channel)", kpi["revenue_total"], r["bychannel_rev"]),
        ("kpi.revenue == sum(sales_category)", kpi["revenue_total"], r["bycategory_rev"]),
        ("kpi.revenue == sum(new+returning rev)", kpi["revenue_total"], r["newret_rev"]),
        # channel decomposition + orders
        ("in-store + online == total revenue",
         (_n(sk["revenue_instore"]) or 0) + (_n(sk["revenue_online"]) or 0), sk["revenue_total"]),
        ("new + returning orders == orders_total",
         (_n(sk["new_orders"]) or 0) + (_n(sk["returning_orders"]) or 0), sk["orders_total"]),
        ("sum(new_returning orders) == orders_total", r["newret_orders"], sk["orders_total"]),
        # GA4 sessions invariant
        ("kpi.sessions == sum(ga4_channels)", kpi["sessions"], r["ga4ch_sessions"]),
        ("kpi.sessions == ga4_funnel.sessions", kpi["sessions"], fn["sessions"]),
        ("kpi.sessions == sum(ga4_monthly_channel)", kpi["sessions"], r["ga4mo_sessions"]),
        # raw cross-check (independent of the staging views)
        ("RAW Google spend == platform_summary", r["raw_google"], g.get("spend_aud")),
        ("RAW Meta spend == platform_summary", r["raw_meta"], m.get("spend_aud")),
        ("RAW TTD spend == platform_summary", r["raw_ttd"], t.get("spend_aud")),
        ("RAW total ad spend == kpi.ad_spend", raw_ad, kpi["ad_spend"]),
        ("RAW v_sales revenue == kpi.revenue", r["raw_sales_rev"], kpi["revenue_total"]),
    ]

    print("\n\nReconciliation checks (expected == actual)\n")
    nw = max(len(c[0]) for c in checks)
    fails = 0
    for label, a, b in checks:
        ok = close(a, b)
        fails += 0 if ok else 1
        delta = (_n(a) or 0) - (_n(b) or 0)
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {label:<{nw}}  {_n(a) or 0:>16,.2f}  vs {_n(b) or 0:>16,.2f}"
              + ("" if ok else f"   delta {delta:,.2f}"))

    # ---- raw row counts (informational) + reference snapshot ---------------
    c = q(f"""
    SELECT
      (SELECT COUNT(*) FROM {D}.stg_sales`) sales,
      (SELECT COUNT(*) FROM {D}.stg_google`) google,
      (SELECT COUNT(*) FROM {D}.stg_ga4`) ga4,
      (SELECT COUNT(*) FROM {D}.stg_meta`) meta,
      (SELECT COUNT(*) FROM {D}.stg_ttd`) ttd,
      (SELECT COUNT(*) FROM `{PROJECT}.raw_ga4.perf_ga4_events`
        WHERE client_slug='city-perfume' AND metric_date >= DATE '{WIN}') ga4_events
    """)[0]
    print("\n\nStaging row counts (informational; grow with daily data except TTD pilot)")
    print(f"  stg_sales {c['sales']:,} | stg_google {c['google']:,} | stg_ga4 {c['ga4']:,} | "
          f"ga4_events {c['ga4_events']:,} | stg_meta {c['meta']:,} | stg_ttd {c['ttd']:,}")
    print("  build ref (2026-06-06): sales 358,695 | google 22,117 | ga4 59,463 | "
          "ga4_events 13,620 | meta 2,801 | ttd 105")

    print("\nHeadline vs build-time reference (live should be >= ref as data refreshes):")
    print(f"  revenue A${_n(kpi['revenue_total']):,.0f} (ref A${REF['revenue_total']:,}) | "
          f"ad spend A${_n(kpi['ad_spend']):,.0f} (ref A${REF['ad_spend']:,}) | "
          f"orders {_n(kpi['orders_total']):,.0f} (ref {REF['orders_total']:,}) | "
          f"blended ROAS {_n(kpi['roas_blended']):.1f}x (ref {REF['roas_blended']}x)")

    print(f"\n{len(checks) - fails}/{len(checks)} checks passed."
          + ("" if not fails else f"  {fails} FAILED - see above.") + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())