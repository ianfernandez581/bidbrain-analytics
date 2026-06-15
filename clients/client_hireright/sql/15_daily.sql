-- HireRight - daily delivery series (one row per day over the data span). Mirrors
-- `monthly` (06) / `weekly` (07) at the finest grain so the two monthly trend charts
-- (Overview hero + Paid Media monthly delivery) can offer a Day view. Pure paid
-- media: per-platform impressions plus blended ad impressions / clicks / spend (USD).
-- The day spine comes from the unified delivery so a day with any platform delivering
-- appears once. ad_* folds all three in (spend in USD; each stg_* view already
-- converted). day key is an ISO 'YYYY-MM-DD' string to match the dashboard's
-- inRangeDay helper.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.daily` AS
WITH
d AS (
  SELECT FORMAT_DATE('%Y-%m-%d', metric_date) AS day
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery` GROUP BY day
),
dv AS (
  SELECT FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_usd) AS dv_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_dv360` GROUP BY day
),
td AS (
  SELECT FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_usd) AS td_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_tradedesk` GROUP BY day
),
li AS (
  SELECT FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_hireright.stg_linkedin` GROUP BY day
)
SELECT
  d.day,
  IFNULL(dv.dv_imps, 0) AS dv_imps,
  IFNULL(td.td_imps, 0) AS td_imps,
  IFNULL(li.li_imps, 0) AS li_imps,
  IFNULL(dv.dv_imps,0)      + IFNULL(td.td_imps,0)      + IFNULL(li.li_imps,0)      AS ad_imps,
  IFNULL(dv.dv_clicks,0)    + IFNULL(td.td_clicks,0)    + IFNULL(li.li_clicks,0)    AS ad_clicks,
  IFNULL(dv.dv_spend_usd,0) + IFNULL(td.td_spend_usd,0) + IFNULL(li.li_cost_usd,0)  AS ad_spend_usd
FROM d
LEFT JOIN dv USING (day)
LEFT JOIN td USING (day)
LEFT JOIN li USING (day)
ORDER BY day;
