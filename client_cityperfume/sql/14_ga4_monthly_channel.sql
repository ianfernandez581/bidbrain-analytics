-- City Perfume — GA4 sessions by coarse channel bucket per month (Website tab stacked
-- trend; makes the Oct-2025 tracking break visible). All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_monthly_channel` AS
SELECT
  DATE_TRUNC(metric_date, MONTH) AS month,
  channel_bucket,
  SUM(sessions)                  AS sessions,
  SUM(purchase_revenue)          AS purchase_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
GROUP BY month, channel_bucket
ORDER BY month, channel_bucket;
