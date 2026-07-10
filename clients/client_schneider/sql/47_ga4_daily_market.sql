-- Schneider Electric — GA4 daily sessions (whole property), the Day grain behind the Website tab's
-- "VIEW BY" toggle (the dashboard buckets it up to Month/Week/Day client-side). SHIPPED DISABLED
-- (0 rows until stg_ga4's property placeholder is set). Whole-site single 'All' market. Mirrors
-- client_vmch/sql/32.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_daily_market` AS
SELECT
  metric_date AS day,
  'All' AS market,
  SUM(sessions)         AS ga4_sessions,
  SUM(engaged_sessions) AS engaged_sessions,
  SUM(conversions)      AS conversions,
  SUM(IF(channel_bucket = 'Paid',    sessions, 0))                        AS paid_sessions,
  SUM(IF(channel_bucket = 'Organic', sessions, 0))                        AS organic_sessions,
  SUM(IF(channel_bucket = 'Direct',  sessions, 0))                        AS direct_sessions,
  SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
GROUP BY day
ORDER BY day;
