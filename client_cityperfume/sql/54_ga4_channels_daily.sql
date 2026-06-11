-- City Perfume — GA4 sessions & ecommerce by channel group per DAY (range-aware source for the
-- Website-tab headline cards, channel bars, revenue donut, and the sessions-by-bucket trend).
-- Day grain; the dashboard clips + re-aggregates per channel and buckets the trend. Carries
-- channel_bucket for colouring. Additive columns only. Caveat: GA4 degraded from ~Oct 2025.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_channels_daily` AS
SELECT
  metric_date               AS day,
  channel_group,
  ANY_VALUE(channel_bucket) AS channel_bucket,
  SUM(sessions)             AS sessions,
  SUM(engaged_sessions)     AS engaged_sessions,
  SUM(transactions)         AS transactions,
  SUM(purchase_revenue)     AS purchase_revenue,
  SUM(ecommerce_purchases)  AS ecommerce_purchases
FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
GROUP BY day, channel_group
ORDER BY day, sessions DESC;
