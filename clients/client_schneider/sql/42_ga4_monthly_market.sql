-- Schneider Electric — GA4 monthly sessions (whole property). SHIPPED DISABLED (0 rows until stg_ga4's
-- property placeholder is set). Whole-site single 'All' market. Mirrors client_vmch/sql/14.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_monthly_market` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date) AS month,
  'All' AS market,
  SUM(sessions)                                                           AS sessions,
  SUM(IF(channel_bucket = 'Paid',    sessions, 0))                        AS paid_sessions,
  SUM(IF(channel_bucket = 'Organic', sessions, 0))                        AS organic_sessions,
  SUM(IF(channel_bucket = 'Direct',  sessions, 0))                        AS direct_sessions,
  SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
  SUM(IF(channel_group = 'Display',     sessions, 0))                     AS display_sessions,
  SUM(IF(channel_group = 'Paid Social', sessions, 0))                     AS social_sessions,
  SUM(IF(channel_group = 'Paid Search', sessions, 0))                     AS search_sessions,
  SUM(engaged_sessions) AS engaged_sessions,
  SUM(total_users)      AS users,
  SUM(conversions)      AS conversions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
GROUP BY month
ORDER BY month;
