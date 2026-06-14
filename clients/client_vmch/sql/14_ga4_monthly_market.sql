-- VMCH — GA4 monthly sessions (from 2025-01). Single "Australia" market row.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_monthly_market` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date) AS month,
  'Australia' AS market,
  SUM(sessions) AS sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS paid_sessions,
  SUM(IF(channel_bucket = 'Organic', sessions, 0)) AS organic_sessions,
  SUM(IF(channel_bucket = 'Direct', sessions, 0)) AS direct_sessions,
  SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0)) AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions,
  SUM(engaged_sessions) AS engaged_sessions,
  SUM(total_users) AS users,
  SUM(conversions) AS conversions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2025-01-01'
GROUP BY month
ORDER BY month;