-- City Perfume — headline KPI row (the single row the dashboard reads for the big numbers).
--
-- Window = 2025-06-01 -> latest sales day (applied in every stg_*). ALL AUD, no FX.
--
-- ATTRIBUTION STANCE (blended / marketing-efficiency-ratio):
--   * v_sales is the SINGLE source of truth for revenue / margin / orders / AOV / customers.
--   * roas_blended = total sales revenue / total ad spend (the MER — no per-channel
--     attribution assumed; respects the omnichannel halo onto in-store).
--   * roas_online = online-only revenue (excl. In-store POS) / total ad spend — the
--     secondary, stricter "ad-attributable" lens.
--   * google_rev_claimed / meta_rev_claimed are each platform's OWN-CLAIMED revenue,
--     surfaced for context and NEVER summed into the headline.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.kpi` AS
WITH
ad AS (
  SELECT
    SUM(spend_aud)                              AS ad_spend,
    SUM(IF(platform = 'google', spend_aud, 0))  AS google_spend,
    SUM(IF(platform = 'meta',   spend_aud, 0))  AS meta_spend,
    SUM(IF(platform = 'ttd',    spend_aud, 0))  AS ttd_spend,
    SUM(imps)                                   AS ad_imps,
    SUM(clicks)                                 AS ad_clicks,
    SUM(IF(platform = 'google', platform_revenue, 0))     AS google_rev_claimed,
    SUM(IF(platform = 'meta',   platform_revenue, 0))     AS meta_rev_claimed,
    SUM(IF(platform = 'ttd',    platform_conversions, 0)) AS ttd_conversions
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
),
ga AS (
  SELECT
    SUM(sessions)                                   AS sessions,
    SUM(IF(channel_bucket = 'Paid', sessions, 0))   AS paid_sessions,
    SUM(ecommerce_purchases)                        AS ga4_purchases,
    SUM(purchase_revenue)                           AS ga4_revenue
  FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
),
sa AS (
  SELECT
    SUM(line_total)                                                     AS revenue_total,
    SUM(IF(channel_group != 'In-store POS', line_total, 0))             AS revenue_online,
    SUM(IF(channel_group = 'Website',       line_total, 0))             AS revenue_website,
    SUM(margin)                                                        AS margin_total,
    SUM(quantity)                                                      AS units,
    COUNT(DISTINCT order_id)                                           AS orders_total,
    COUNT(DISTINCT IF(channel_group != 'In-store POS', order_id, NULL)) AS orders_online,
    COUNT(DISTINCT customer_id)                                        AS customers_total,
    COUNT(DISTINCT IF(is_new_customer_order,      order_id,    NULL))  AS new_orders,
    COUNT(DISTINCT IF(NOT is_new_customer_order,  order_id,    NULL))  AS returning_orders,
    COUNT(DISTINCT IF(is_new_customer_order,      customer_id, NULL))  AS new_customers,
    COUNT(DISTINCT IF(NOT is_new_customer_order,  customer_id, NULL))  AS returning_customers,
    MAX(order_date)                                                    AS window_end
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
)
SELECT
  DATE '2025-01-01'                                   AS window_start,
  sa.window_end,
  DATE_DIFF(sa.window_end, DATE '2025-01-01', DAY) + 1 AS window_days,
  -- media
  ad.ad_spend, ad.google_spend, ad.meta_spend, ad.ttd_spend,
  ad.ad_imps, ad.ad_clicks,
  SAFE_DIVIDE(ad.ad_clicks, ad.ad_imps)               AS ctr,
  -- platform-claimed (context only, never summed)
  ad.google_rev_claimed, ad.meta_rev_claimed, ad.ttd_conversions,
  -- sales truth
  sa.revenue_total, sa.revenue_online, sa.revenue_website,
  sa.margin_total,
  SAFE_DIVIDE(sa.margin_total, sa.revenue_total)      AS margin_pct,
  sa.orders_total, sa.orders_online, sa.units,
  SAFE_DIVIDE(sa.revenue_total, sa.orders_total)      AS aov,
  -- blended ROAS (headline = MER on total sales; online = stricter lens)
  SAFE_DIVIDE(sa.revenue_total,  ad.ad_spend)         AS roas_blended,
  SAFE_DIVIDE(sa.revenue_online, ad.ad_spend)         AS roas_online,
  SAFE_DIVIDE(ad.ad_spend, sa.orders_total)           AS cost_per_order,
  -- customers / loyalty
  sa.customers_total, sa.new_customers, sa.returning_customers,
  sa.new_orders, sa.returning_orders,
  SAFE_DIVIDE(sa.returning_orders, sa.orders_total)   AS repeat_order_rate,
  -- GA4 site context (caveat: tracking degraded from Oct 2025)
  ga.sessions, ga.paid_sessions, ga.ga4_purchases, ga.ga4_revenue,
  SAFE_DIVIDE(ga.ga4_purchases, ga.sessions)          AS ga4_cvr
FROM ad CROSS JOIN ga CROSS JOIN sa;
