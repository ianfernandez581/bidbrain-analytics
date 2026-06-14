-- TLM — weekly ad-delivery + revenue correlation series (campaign window).
--
-- One row per ISO week (Mon-anchored). Pairs the week's Google Ads delivery (conversions
-- + revenue — the e-commerce signal) with Trade Desk delivery (spend/imps/clicks only).
-- From 2025-08-01 (window start per EDA). This is what the Performance tab plots and
-- correlates. Per-platform impressions kept so the Platform filter can recompute the ad
-- series client-side. NO website/sessions layer — TLM has no GA4.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.weekly` AS
WITH
ga AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)        AS g_imps,
    SUM(clicks)      AS g_clicks,
    SUM(spend_aud)   AS g_spend_aud,
    SUM(conversions) AS g_conv,
    SUM(revenue)     AS g_revenue
  FROM `bidbrain-analytics.client_tlm.stg_google`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY week_start
),
td AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)      AS t_imps,
    SUM(clicks)    AS t_clicks,
    SUM(spend_aud) AS t_spend_aud
  FROM `bidbrain-analytics.client_tlm.stg_ttd`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY week_start
)
SELECT
  COALESCE(ga.week_start, td.week_start) AS week_start,
  IFNULL(ga.g_imps, 0)    AS g_imps,
  IFNULL(ga.g_clicks, 0)  AS g_clicks,
  IFNULL(ga.g_spend_aud, 0) AS g_spend_aud,
  IFNULL(ga.g_conv, 0)    AS g_conv,
  IFNULL(ga.g_revenue, 0) AS g_revenue,
  IFNULL(td.t_imps, 0)    AS t_imps,
  IFNULL(td.t_clicks, 0)  AS t_clicks,
  IFNULL(td.t_spend_aud, 0) AS t_spend_aud,
  -- Combined
  IFNULL(ga.g_imps,0)      + IFNULL(td.t_imps,0)      AS imps,
  IFNULL(ga.g_clicks,0)    + IFNULL(td.t_clicks,0)    AS clicks,
  IFNULL(ga.g_spend_aud,0) + IFNULL(td.t_spend_aud,0) AS spend_aud,
  IFNULL(ga.g_conv, 0)     AS conversions,
  IFNULL(ga.g_revenue, 0)  AS revenue
FROM ga
FULL OUTER JOIN td USING (week_start)
ORDER BY week_start;