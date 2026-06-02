-- STT GDC — monthly trend (Jan 2025 → now): the hero "ads vs website traffic" series.
--
-- One row per month, GA4 sessions split by bucket (and the two ad-mapped channels
-- Display = DV360, Paid Social = LinkedIn) alongside the LinkedIn + DV360 delivery
-- for the same month. Starts at 2025-01 so the chart shows a pre-campaign baseline
-- before the paid programmatic ramp. ad_spend_sgd folds LinkedIn USD in at FX.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.monthly` AS
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
  FROM `bidbrain-analytics.client_stt.stg_ga4`
  WHERE metric_date >= DATE '2025-01-01'
  GROUP BY month
),
li AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_stt.stg_linkedin` GROUP BY month
),
dv AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_sgd) AS dv_spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_dv360` GROUP BY month
)
SELECT
  g.*,
  IFNULL(li.li_imps, 0)     AS li_imps,
  IFNULL(li.li_clicks, 0)   AS li_clicks,
  IFNULL(li.li_cost_usd, 0) AS li_cost_usd,
  IFNULL(dv.dv_imps, 0)     AS dv_imps,
  IFNULL(dv.dv_clicks, 0)   AS dv_clicks,
  IFNULL(dv.dv_spend_sgd, 0) AS dv_spend_sgd,
  IFNULL(li.li_imps, 0)   + IFNULL(dv.dv_imps, 0)               AS ad_imps,
  IFNULL(li.li_clicks, 0) + IFNULL(dv.dv_clicks, 0)             AS ad_clicks,
  IFNULL(dv.dv_spend_sgd, 0) + IFNULL(li.li_cost_usd, 0) * 1.34 AS ad_spend_sgd
FROM g
LEFT JOIN li USING (month)
LEFT JOIN dv USING (month)
ORDER BY month;
