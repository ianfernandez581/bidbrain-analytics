-- City Perfume — GA4 sessions & ecommerce by channel group (Website tab). One row per
-- GA4 default channel group, with its coarse Paid/Organic/Direct/Referral/Email/Other
-- bucket. Caveat: GA4 tracking degraded from Oct 2025 (dashboard flags this).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_channels` AS
SELECT
  channel_group,
  ANY_VALUE(channel_bucket)   AS channel_bucket,
  SUM(sessions)               AS sessions,
  SUM(engaged_sessions)       AS engaged_sessions,
  SUM(transactions)           AS transactions,
  SUM(purchase_revenue)       AS purchase_revenue,
  SUM(ecommerce_purchases)    AS ecommerce_purchases
FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
GROUP BY channel_group
ORDER BY sessions DESC;
