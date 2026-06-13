-- STT GDC — GA4 monthly sessions BY market (from 2025-01), for the Country-filtered trend charts.
-- The dashboard sums the selected countries per month onto the (whole-campaign) ad series.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_monthly_market` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date) AS month,
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
WHERE metric_date >= DATE '2025-01-01'
GROUP BY month, market
ORDER BY month, market;
