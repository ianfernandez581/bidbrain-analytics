"""EDA queries for The Little Marionette — verify exact names, volumes, schemas."""
from google.cloud import bigquery

bq = bigquery.Client(project="bidbrain-analytics", location="australia-southeast1")

def run(sql, label):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    rows = list(bq.query(sql).result())
    if not rows:
        print("  (no rows returned)")
        return
    for r in rows:
        d = dict(r)
        print("  " + " | ".join(f"{k}={v}" for k, v in d.items()))
    print(f"  ({len(rows)} rows)")
    return rows

# 1. TTD advertiser name check
run("""
SELECT advertiser_name, COUNT(*) AS nrows, MIN(metric_date) AS min_d, MAX(metric_date) AS max_d,
       SUM(impressions) AS imps, SUM(clicks) AS clk, SUM(cost) AS cost, ANY_VALUE(currency) AS ccy
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE LOWER(advertiser_name) LIKE '%marionette%'
GROUP BY advertiser_name
""", "TTD advertiser check (LIKE '%marionette%')")

# 2. Google Ads account name check
run("""
SELECT account_name, COUNT(*) AS nrows, MIN(metric_date) AS min_d, MAX(metric_date) AS max_d,
       SUM(impressions) AS imps, SUM(clicks) AS clk, SUM(spend) AS spend,
       SUM(conversions) AS conv, SUM(conversions_value) AS revenue, ANY_VALUE(currency_code) AS ccy
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE LOWER(account_name) LIKE '%marionette%'
GROUP BY account_name
""", "Google Ads account check (LIKE '%marionette%')")

# 3. Google Ads column list
run("""
SELECT column_name, data_type
FROM `bidbrain-analytics.raw_google_ads`.INFORMATION_SCHEMA.COLUMNS
WHERE table_name = 'perf_google_ads'
ORDER BY ordinal_position
""", "Google Ads column list (perf_google_ads)")

# 4. Google Ads by campaign_type
run("""
SELECT campaign_type, COUNT(DISTINCT campaign_name) AS campaigns,
       SUM(impressions) AS imps, SUM(clicks) AS clk, SUM(spend) AS spend,
       SUM(conversions) AS conv, SUM(conversions_value) AS revenue,
       SAFE_DIVIDE(SUM(conversions_value), SUM(spend)) AS roas
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE account_name = 'The Little Marionette'
GROUP BY campaign_type
ORDER BY spend DESC
""", "Google Ads by campaign_type (WHERE account_name = 'The Little Marionette')")

# 5. Sanity check: CPM
run("""
SELECT SAFE_DIVIDE(SUM(spend), SUM(impressions)) * 1000 AS cpm
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE account_name = 'The Little Marionette'
""", "Google Ads CPM sanity check (should be ~A$1-50)")

# 6. TTD detail
run("""
SELECT ANY_VALUE(currency) AS ccy,
       COUNT(DISTINCT campaign_name) AS campaigns,
       COUNT(DISTINCT ad_format) AS formats,
       COUNTIF(conversions IS NOT NULL) AS rows_with_conv,
       SUM(video_starts) AS vs, SUM(video_completes) AS vc
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE advertiser_name = 'The Little Marionette'
""", "TTD detail (currency, campaigns, formats, video, conversions)")

print("\n\nEDA COMPLETE.")