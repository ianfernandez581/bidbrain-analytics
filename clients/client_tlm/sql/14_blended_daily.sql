-- TLM — daily trend: the hero "ad spend vs revenue / ROAS" series at day grain.
--
-- One row per day. Mirrors `monthly` (05_monthly.sql) but keyed on the raw metric_date
-- ('YYYY-MM-DD') instead of FORMAT_DATE('%Y-%m'). Pairs Google Ads delivery (conversions +
-- revenue = the e-commerce story) with Trade Desk delivery (spend/imps/clicks only). From
-- 2025-08-01 (window start per EDA, matching `weekly`). ad_* folds the two platforms
-- together. NO website/GA4 layer. ROAS / AOV / CPA are derived client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.daily` AS
WITH
ga AS (
  SELECT
    metric_date      AS day,
    SUM(imps)        AS g_imps,
    SUM(clicks)      AS g_clicks,
    SUM(spend_aud)   AS g_spend_aud,
    SUM(conversions) AS g_conv,
    SUM(revenue)     AS g_revenue
  FROM `bidbrain-analytics.client_tlm.stg_google`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY day
),
td AS (
  SELECT
    metric_date    AS day,
    SUM(imps)      AS t_imps,
    SUM(clicks)    AS t_clicks,
    SUM(spend_aud) AS t_spend_aud
  FROM `bidbrain-analytics.client_tlm.stg_ttd`
  WHERE metric_date >= DATE '2025-08-01'
  GROUP BY day
)
SELECT
  COALESCE(ga.day, td.day)    AS day,
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
FULL OUTER JOIN td USING (day)
ORDER BY day;
