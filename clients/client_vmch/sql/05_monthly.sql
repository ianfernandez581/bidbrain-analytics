-- VMCH — monthly trend (Jan 2025 → now): GA4 sessions vs TTD delivery.
-- One row per month. GA4 by channel bucket, TTD delivery.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.monthly` AS
WITH
g AS (
  SELECT
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(sessions)                                                      AS sessions,
    SUM(IF(channel_bucket = 'Paid',    sessions, 0))                   AS paid_sessions,
    SUM(IF(channel_bucket = 'Organic', sessions, 0))                   AS organic_sessions,
    SUM(IF(channel_bucket = 'Direct',  sessions, 0))                   AS direct_sessions,
    SUM(IF(channel_bucket NOT IN ('Paid','Organic','Direct'), sessions, 0)) AS other_sessions,
    SUM(IF(channel_group = 'Display',     sessions, 0))                AS display_sessions,
    SUM(IF(channel_group = 'Paid Social', sessions, 0))                AS social_sessions,
    SUM(engaged_sessions) AS engaged_sessions,
    SUM(total_users)      AS users,
    SUM(conversions)      AS conversions
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2025-01-01'
  GROUP BY month
),
ttd AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS ttd_imps, SUM(clicks) AS ttd_clicks, SUM(spend_aud) AS ttd_spend_aud
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery` GROUP BY month   -- incl. MODELLED April (03b/03c)
)
SELECT
  g.*,
  IFNULL(ttd.ttd_imps, 0)      AS ttd_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ttd_clicks,
  IFNULL(ttd.ttd_spend_aud, 0) AS ttd_spend_aud,
  IFNULL(ttd.ttd_imps, 0)      AS ad_imps,
  IFNULL(ttd.ttd_clicks, 0)    AS ad_clicks,
  IFNULL(ttd.ttd_spend_aud, 0) AS ad_spend_aud
FROM g
LEFT JOIN ttd USING (month)
ORDER BY month;