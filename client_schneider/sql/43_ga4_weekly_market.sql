-- Schneider Electric — GA4 weekly sessions BY market (campaign window). SHIPPED DISABLED
-- (0 rows until stg_ga4's property placeholder is set). Mirrors client_STT/sql/15.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_weekly_market` AS
SELECT
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  market,
  SUM(sessions)                                       AS ga4_sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY week_start, market
ORDER BY week_start, market;
