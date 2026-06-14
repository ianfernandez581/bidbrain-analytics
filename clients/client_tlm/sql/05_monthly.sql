-- TLM — monthly trend: the hero "ad spend vs revenue / ROAS" series.
--
-- One row per month. Pairs Google Ads delivery (conversions + revenue are the e-commerce
-- story) with Trade Desk delivery (spend/imps/clicks only). From 2025-08 (the start of
-- the live data per EDA). ad_* folds the two platforms together. NO website/GA4 layer.
-- ROAS / AOV / CPA are derived client-side from these additive base metrics.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.monthly` AS
WITH
ga AS (
  SELECT
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)        AS g_imps,
    SUM(clicks)      AS g_clicks,
    SUM(spend_aud)   AS g_spend_aud,
    SUM(conversions) AS g_conv,
    SUM(revenue)     AS g_revenue
  FROM `bidbrain-analytics.client_tlm.stg_google`
  GROUP BY month
),
td AS (
  SELECT
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS t_imps,
    SUM(clicks)    AS t_clicks,
    SUM(spend_aud) AS t_spend_aud
  FROM `bidbrain-analytics.client_tlm.stg_ttd`
  GROUP BY month
)
SELECT
  COALESCE(ga.month, td.month) AS month,
  IFNULL(ga.g_imps, 0)        AS g_imps,
  IFNULL(ga.g_clicks, 0)      AS g_clicks,
  IFNULL(ga.g_spend_aud, 0)   AS g_spend_aud,
  IFNULL(ga.g_conv, 0)        AS g_conv,
  IFNULL(ga.g_revenue, 0)     AS g_revenue,
  IFNULL(td.t_imps, 0)        AS t_imps,
  IFNULL(td.t_clicks, 0)      AS t_clicks,
  IFNULL(td.t_spend_aud, 0)   AS t_spend_aud,
  -- Combined
  IFNULL(ga.g_imps,0)       + IFNULL(td.t_imps,0)       AS imps,
  IFNULL(ga.g_clicks,0)     + IFNULL(td.t_clicks,0)     AS clicks,
  IFNULL(ga.g_spend_aud,0)  + IFNULL(td.t_spend_aud,0)  AS spend_aud,
  IFNULL(ga.g_conv, 0)                                    AS conversions,
  IFNULL(ga.g_revenue, 0)                                 AS revenue
FROM ga
FULL OUTER JOIN td USING (month)
ORDER BY month;