-- Schneider Electric — GA4 weekly sessions (whole property). SHIPPED DISABLED (0 rows until stg_ga4's
-- property placeholder is set). Whole-site single 'All' market. Mirrors client_vmch/sql/15.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_weekly_market` AS
SELECT
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  'All' AS market,
  SUM(sessions)                                       AS ga4_sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0)) AS search_sessions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
GROUP BY week_start
ORDER BY week_start;
