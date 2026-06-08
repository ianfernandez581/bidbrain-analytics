-- City Perfume — weekly trend (ISO week, Monday-anchored) for the Ads -> Revenue tab:
-- weekly ad spend vs sales revenue (correlation scatter + dual-axis line). All AUD.
-- Sales has no campaign dimension, so the sales columns are whole-store every week; only
-- the ad columns rescale under the Campaign filter (the dashboard recomputes client-side).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.weekly` AS
WITH
ad AS (
  SELECT
    DATE_TRUNC(metric_date, WEEK(MONDAY))       AS week_start,
    SUM(spend_aud)                              AS ad_spend,
    SUM(IF(platform = 'google', spend_aud, 0))  AS google_spend,
    SUM(IF(platform = 'meta',   spend_aud, 0))  AS meta_spend,
    SUM(IF(platform = 'ttd',    spend_aud, 0))  AS ttd_spend,
    SUM(clicks)                                 AS ad_clicks
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
  GROUP BY week_start
),
sa AS (
  SELECT
    DATE_TRUNC(order_date, WEEK(MONDAY))                     AS week_start,
    SUM(line_total)                                         AS revenue_total,
    SUM(IF(channel_group != 'In-store POS', line_total, 0)) AS revenue_online,
    SUM(margin)                                            AS margin,
    COUNT(DISTINCT order_id)                               AS orders
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
  GROUP BY week_start
)
SELECT
  week_start,
  COALESCE(ad.ad_spend, 0)        AS ad_spend,
  COALESCE(ad.google_spend, 0)    AS google_spend,
  COALESCE(ad.meta_spend, 0)      AS meta_spend,
  COALESCE(ad.ttd_spend, 0)       AS ttd_spend,
  COALESCE(ad.ad_clicks, 0)       AS ad_clicks,
  COALESCE(sa.revenue_total, 0)   AS revenue_total,
  COALESCE(sa.revenue_online, 0)  AS revenue_online,
  COALESCE(sa.margin, 0)          AS margin,
  COALESCE(sa.orders, 0)          AS orders,
  SAFE_DIVIDE(sa.revenue_total,  ad.ad_spend) AS roas_blended,
  SAFE_DIVIDE(sa.revenue_online, ad.ad_spend) AS roas_online,
  SAFE_DIVIDE(ad.ad_spend, sa.orders)         AS cost_per_order
FROM ad
FULL OUTER JOIN sa USING (week_start)
ORDER BY week_start;
