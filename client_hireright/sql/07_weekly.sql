-- HireRight - weekly delivery series (one row per ISO week, Monday-anchored, over
-- the data span). Pure paid media: per-platform impressions plus blended ad
-- impressions / clicks / spend (USD). Kept for completeness + the CSV export
-- (the 2-tab dashboard charts monthly, not weekly).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.weekly` AS
WITH
dv AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_usd) AS dv_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_dv360` GROUP BY week_start
),
td AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_usd) AS td_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_tradedesk` GROUP BY week_start
),
li AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_hireright.stg_linkedin` GROUP BY week_start
),
w AS (
  SELECT DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery` GROUP BY week_start
)
SELECT
  w.week_start,
  IFNULL(dv.dv_imps, 0) AS dv_imps,
  IFNULL(td.td_imps, 0) AS td_imps,
  IFNULL(li.li_imps, 0) AS li_imps,
  IFNULL(dv.dv_imps,0)      + IFNULL(td.td_imps,0)      + IFNULL(li.li_imps,0)      AS ad_imps,
  IFNULL(dv.dv_clicks,0)    + IFNULL(td.td_clicks,0)    + IFNULL(li.li_clicks,0)    AS ad_clicks,
  IFNULL(dv.dv_spend_usd,0) + IFNULL(td.td_spend_usd,0) + IFNULL(li.li_cost_usd,0)  AS ad_spend_usd
FROM w
LEFT JOIN dv USING (week_start)
LEFT JOIN td USING (week_start)
LEFT JOIN li USING (week_start)
ORDER BY week_start;
