-- STT GDC — DAILY ads-vs-traffic series (campaign window). Day-grain mirror of
-- `monthly` (05) + `weekly` (12): the dashboard's "VIEW BY → Day" toggle reads this
-- so the hero / web-trend charts can drill to daily resolution. One row per
-- metric_date. Carries the same GA4 session split + LinkedIn/DV360/Google delivery
-- as the coarser views, so the day branch sums identically. From 2025-06-01 (the
-- campaign window) to keep the day list bounded — day grain is only meaningful in
-- the active flight, and the monthly view already shows the 2025-01 baseline.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.daily` AS
WITH
g AS (
  SELECT
    metric_date AS day,
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
  WHERE metric_date >= DATE '2025-06-01'
  GROUP BY day
),
li AS (
  SELECT metric_date AS day,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_stt.stg_linkedin`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY day
),
dv AS (
  SELECT metric_date AS day,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_sgd) AS dv_spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_dv360`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY day
),
ga AS (
  SELECT metric_date AS day,
         SUM(imps) AS ga_imps, SUM(clicks) AS ga_clicks, SUM(spend_sgd) AS ga_spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_google`
  WHERE metric_date >= DATE '2025-06-01' GROUP BY day
)
SELECT
  g.*,
  IFNULL(li.li_imps, 0)     AS li_imps,
  IFNULL(li.li_clicks, 0)   AS li_clicks,
  IFNULL(li.li_cost_usd, 0) AS li_cost_usd,
  IFNULL(dv.dv_imps, 0)     AS dv_imps,
  IFNULL(dv.dv_clicks, 0)   AS dv_clicks,
  IFNULL(dv.dv_spend_sgd, 0) AS dv_spend_sgd,
  IFNULL(ga.ga_imps, 0)     AS ga_imps,
  IFNULL(ga.ga_clicks, 0)   AS ga_clicks,
  IFNULL(ga.ga_spend_sgd, 0) AS ga_spend_sgd,
  IFNULL(li.li_imps, 0)   + IFNULL(dv.dv_imps, 0)   + IFNULL(ga.ga_imps, 0)   AS ad_imps,
  IFNULL(li.li_clicks, 0) + IFNULL(dv.dv_clicks, 0) + IFNULL(ga.ga_clicks, 0) AS ad_clicks,
  IFNULL(dv.dv_spend_sgd, 0) + IFNULL(li.li_cost_usd, 0) + IFNULL(ga.ga_spend_sgd, 0) AS ad_spend_sgd
FROM g
LEFT JOIN li USING (day)
LEFT JOIN dv USING (day)
LEFT JOIN ga USING (day)
ORDER BY day;
