-- VMCH — GA4 daily sessions, single "Australia" market. Mirrors 15_ga4_weekly_market.sql
-- at metric_date grain (vestigial single-row market; kept for parity with the weekly/monthly views).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_daily_market` AS
SELECT
  metric_date AS day,
  'Australia' AS market,
  SUM(sessions) AS ga4_sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0)) AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
GROUP BY day
ORDER BY day;
