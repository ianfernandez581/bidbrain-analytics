-- STT GDC — GA4 DAILY sessions BY market (campaign window). Day-grain mirror of
-- ga4_monthly_market (14) + ga4_weekly_market (15): the dashboard sums the selected
-- countries per day onto the (whole-campaign) ad series when "VIEW BY → Day" is set.
-- Same session split as the coarser views. From 2025-06-01 to bound the day list.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_daily_market` AS
SELECT
  metric_date AS day,
  market,
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
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY day, market
ORDER BY day, market;
