-- STT GDC — GA4 weekly sessions BY market (campaign window), for the Country-filtered
-- Ads→Traffic correlation. Sessions on the two ad-mapped channels (Display, Paid Social) per week.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_weekly_market` AS
SELECT
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  market,
  SUM(sessions)                                       AS ga4_sessions,
  SUM(IF(channel_bucket = 'Paid', sessions, 0))       AS paid_sessions,
  SUM(IF(channel_group = 'Display', sessions, 0))     AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0)) AS social_sessions
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY week_start, market
ORDER BY week_start, market;
