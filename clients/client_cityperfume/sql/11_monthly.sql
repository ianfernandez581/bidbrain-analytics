-- City Perfume — monthly trend (month x {ad spend by platform, sessions, sales, margin}).
-- The Overview hero (monthly ad spend by platform vs sales revenue vs ROAS). FULL OUTER
-- JOIN across the three sources on month so a month with sales but no GA4 (post-Oct-2025
-- GA4 break) or vice-versa still appears. All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.monthly` AS
WITH
ad AS (
  SELECT
    DATE_TRUNC(metric_date, MONTH)              AS month,
    SUM(spend_aud)                              AS ad_spend,
    SUM(IF(platform = 'google', spend_aud, 0))  AS google_spend,
    SUM(IF(platform = 'meta',   spend_aud, 0))  AS meta_spend,
    SUM(IF(platform = 'ttd',    spend_aud, 0))  AS ttd_spend,
    SUM(imps)                                   AS ad_imps,
    SUM(clicks)                                 AS ad_clicks
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
  GROUP BY month
),
ga AS (
  SELECT
    DATE_TRUNC(metric_date, MONTH)                  AS month,
    SUM(sessions)                                   AS sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))   AS paid_sessions,
    SUM(purchase_revenue)                           AS ga4_revenue
  FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
  GROUP BY month
),
sa AS (
  SELECT
    DATE_TRUNC(order_date, MONTH)                            AS month,
    SUM(line_total)                                         AS revenue_total,
    SUM(IF(channel_group != 'In-store POS', line_total, 0)) AS revenue_online,
    SUM(margin)                                            AS margin,
    COUNT(DISTINCT order_id)                               AS orders
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
  GROUP BY month
)
SELECT
  month,
  COALESCE(ad.ad_spend, 0)        AS ad_spend,
  COALESCE(ad.google_spend, 0)    AS google_spend,
  COALESCE(ad.meta_spend, 0)      AS meta_spend,
  COALESCE(ad.ttd_spend, 0)       AS ttd_spend,
  COALESCE(ad.ad_imps, 0)         AS ad_imps,
  COALESCE(ad.ad_clicks, 0)       AS ad_clicks,
  COALESCE(ga.sessions, 0)        AS sessions,
  COALESCE(ga.paid_sessions, 0)   AS paid_sessions,
  COALESCE(ga.ga4_revenue, 0)     AS ga4_revenue,
  COALESCE(sa.revenue_total, 0)   AS revenue_total,
  COALESCE(sa.revenue_online, 0)  AS revenue_online,
  COALESCE(sa.margin, 0)          AS margin,
  COALESCE(sa.orders, 0)          AS orders,
  SAFE_DIVIDE(sa.revenue_total,  ad.ad_spend) AS roas_blended,
  SAFE_DIVIDE(sa.revenue_online, ad.ad_spend) AS roas_online
FROM ad
FULL OUTER JOIN ga USING (month)
FULL OUTER JOIN sa USING (month)
ORDER BY month;
