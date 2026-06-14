-- VMCH — GA4 weekly sessions, single "Australia" market.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_weekly_market` AS
SELECT
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  'Australia' AS market,
  SUM(sessions) AS ga4_sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0)) AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0)) AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
GROUP BY week_start
ORDER BY week_start;