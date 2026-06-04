-- HireRight - monthly delivery trend (one row per month over the data span): the
-- hero "spend by platform + clicks" series. Pure paid media - DV360 + TradeDesk +
-- LinkedIn impressions / clicks / spend per month. The month spine comes from the
-- unified delivery so a month with any platform delivering appears once. ad_* folds
-- all three in (spend in USD; each stg_* view already converted).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.monthly` AS
WITH
m AS (
  SELECT DISTINCT FORMAT_DATE('%Y-%m', metric_date) AS month
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
),
dv AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS dv_imps, SUM(clicks) AS dv_clicks, SUM(spend_usd) AS dv_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_dv360` GROUP BY month
),
td AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS td_imps, SUM(clicks) AS td_clicks, SUM(spend_usd) AS td_spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_tradedesk` GROUP BY month
),
li AS (
  SELECT FORMAT_DATE('%Y-%m', metric_date) AS month,
         SUM(imps) AS li_imps, SUM(clicks) AS li_clicks, SUM(cost_usd) AS li_cost_usd
  FROM `bidbrain-analytics.client_hireright.stg_linkedin` GROUP BY month
)
SELECT
  m.month,
  IFNULL(dv.dv_imps, 0)      AS dv_imps,
  IFNULL(dv.dv_clicks, 0)    AS dv_clicks,
  IFNULL(dv.dv_spend_usd, 0) AS dv_spend_usd,
  IFNULL(td.td_imps, 0)      AS td_imps,
  IFNULL(td.td_clicks, 0)    AS td_clicks,
  IFNULL(td.td_spend_usd, 0) AS td_spend_usd,
  IFNULL(li.li_imps, 0)      AS li_imps,
  IFNULL(li.li_clicks, 0)    AS li_clicks,
  IFNULL(li.li_cost_usd, 0)  AS li_cost_usd,
  IFNULL(dv.dv_imps,0)      + IFNULL(td.td_imps,0)      + IFNULL(li.li_imps,0)      AS ad_imps,
  IFNULL(dv.dv_clicks,0)    + IFNULL(td.td_clicks,0)    + IFNULL(li.li_clicks,0)    AS ad_clicks,
  IFNULL(dv.dv_spend_usd,0) + IFNULL(td.td_spend_usd,0) + IFNULL(li.li_cost_usd,0)  AS ad_spend_usd
FROM m
LEFT JOIN dv USING (month)
LEFT JOIN td USING (month)
LEFT JOIN li USING (month)
ORDER BY month;
