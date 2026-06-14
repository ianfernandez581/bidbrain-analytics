"""Trust-the-numbers verification for TLM.

Compares three layers that MUST agree for the dashboard headline to be trustworthy:
  (A) raw tables (sliced to TLM)         -- ground truth
  (B) the kpi view                        -- the 'official' headline row
  (C) SUM(ad_campaign_monthly)            -- what the dashboard ACTUALLY computes for KPIs
Also dumps google_by_type and a couple of consistency checks.
"""
from google.cloud import bigquery

bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")


def one(sql):
    return dict(next(bq.query(sql).result()))


def show(title, d):
    print(f"\n=== {title} ===")
    for k, v in d.items():
        if isinstance(v, float):
            print(f"  {k:18} {v:,.2f}")
        else:
            print(f"  {k:18} {v}")


# (A) RAW ground truth
raw = one("""
SELECT
  (SELECT SUM(impressions) FROM `bidbrain-analytics.raw_google_ads.perf_google_ads` WHERE account_name='The Little Marionette') AS g_imps,
  (SELECT SUM(clicks)      FROM `bidbrain-analytics.raw_google_ads.perf_google_ads` WHERE account_name='The Little Marionette') AS g_clicks,
  (SELECT SUM(spend)       FROM `bidbrain-analytics.raw_google_ads.perf_google_ads` WHERE account_name='The Little Marionette') AS g_spend,
  (SELECT SUM(conversions) FROM `bidbrain-analytics.raw_google_ads.perf_google_ads` WHERE account_name='The Little Marionette') AS g_conv,
  (SELECT SUM(conversions_value) FROM `bidbrain-analytics.raw_google_ads.perf_google_ads` WHERE account_name='The Little Marionette') AS g_rev,
  (SELECT SUM(impressions) FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk` WHERE advertiser_name='The Little Marionette') AS t_imps,
  (SELECT SUM(clicks)      FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk` WHERE advertiser_name='The Little Marionette') AS t_clicks,
  (SELECT SUM(cost)        FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk` WHERE advertiser_name='The Little Marionette') AS t_spend
""")
show("(A) RAW ground truth (Google + TTD)", raw)

# (B) kpi view
kpi = one("SELECT * FROM `bidbrain-analytics.client_tlm.kpi`")
show("(B) kpi view", kpi)

# (C) SUM of ad_campaign_monthly  <-- what dashboard KPIs use
acm = one("""
SELECT
  SUM(IF(platform='google',spend_aud,0)) AS g_spend,
  SUM(IF(platform='ttd',   spend_aud,0)) AS t_spend,
  SUM(spend_aud) AS spend, SUM(imps) AS imps, SUM(clicks) AS clicks,
  SUM(conversions) AS conv, SUM(revenue) AS rev
FROM `bidbrain-analytics.client_tlm.ad_campaign_monthly`
""")
show("(C) SUM(ad_campaign_monthly) -- dashboard KPI source", acm)

# (C2) SUM of monthly view (used for hero labels + revenue line)
mon = one("""
SELECT SUM(spend_aud) AS spend, SUM(imps) AS imps, SUM(clicks) AS clicks,
       SUM(conversions) AS conv, SUM(revenue) AS rev,
       SUM(g_spend_aud) AS g_spend, SUM(t_spend_aud) AS t_spend
FROM `bidbrain-analytics.client_tlm.monthly`
""")
show("(C2) SUM(monthly view)", mon)

# Consistency deltas
print("\n=== DELTAS (should all be ~0) ===")
print(f"  kpi.revenue        - raw.g_rev   = {float(kpi['revenue'])      - float(raw['g_rev']):,.2f}")
print(f"  kpi.ad_spend_aud   - raw spend   = {float(kpi['ad_spend_aud']) - float(raw['g_spend']) - float(raw['t_spend']):,.2f}")
print(f"  SUM(acm).rev       - kpi.revenue = {float(acm['rev'])  - float(kpi['revenue']):,.2f}   <-- if !=0, dashboard headline != kpi view")
print(f"  SUM(acm).spend     - kpi.spend   = {float(acm['spend']) - float(kpi['ad_spend_aud']):,.2f}")
print(f"  SUM(acm).conv      - kpi.conv    = {float(acm['conv'])  - float(kpi['conversions']):,.2f}")
print(f"  SUM(monthly).rev   - kpi.revenue = {float(mon['rev'])  - float(kpi['revenue']):,.2f}")
print(f"  SUM(monthly).spend - kpi.spend   = {float(mon['spend']) - float(kpi['ad_spend_aud']):,.2f}")

# google_by_type
print("\n=== google_by_type ===")
for r in bq.query("SELECT * FROM `bidbrain-analytics.client_tlm.google_by_type`").result():
    d = dict(r)
    roas = (float(d['revenue'])/float(d['spend_aud'])) if d['spend_aud'] else 0
    print(f"  {str(d['campaign_type']):16} spend={float(d['spend_aud']):>10,.0f}  conv={float(d['conversions']):>7,.1f}  rev={float(d['revenue']):>11,.0f}  ROAS={roas:.2f}x")

# rows that ad_campaign_monthly would DROP (imps=0 & clicks=0 & spend=0 but revenue/conv>0)
drop = one("""
SELECT COUNT(*) AS n, SUM(conversions) AS conv, SUM(revenue) AS rev
FROM `bidbrain-analytics.client_tlm.stg_google`
WHERE NOT (imps>0 OR clicks>0 OR spend_aud>0) AND (conversions>0 OR revenue>0)
""")
show("Google rows dropped by 'delivering only' filter but carrying conv/rev", drop)

print("\nDONE.")
