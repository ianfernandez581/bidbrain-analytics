-- City Perfume — first-party sales headline row (Sales & Products tab). Aggregates only —
-- no customer_id/email ever leaves here. New-vs-returning is computed from the order's
-- first-ever-order flag (stg_sales.is_new_customer_order, over full history). Margin is
-- net-as-reported (known caveats: zero-cost-price lines inflate it, promo lines go
-- negative) — surfaced honestly, flagged in the dashboard.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_kpi` AS
SELECT
  SUM(line_total)                                                    AS revenue_total,
  SUM(IF(channel_group != 'In-store POS', line_total, 0))            AS revenue_online,
  SUM(IF(channel_group = 'Website',       line_total, 0))            AS revenue_website,
  SUM(IF(channel_group = 'In-store POS',  line_total, 0))            AS revenue_instore,
  SUM(IF(channel_group = 'Marketplace',   line_total, 0))            AS revenue_marketplace,
  SUM(margin)                                                        AS margin_total,
  SAFE_DIVIDE(SUM(margin), SUM(line_total))                          AS margin_pct,
  COUNT(DISTINCT order_id)                                           AS orders_total,
  SAFE_DIVIDE(SUM(line_total), COUNT(DISTINCT order_id))             AS aov,
  SUM(quantity)                                                      AS units,
  SAFE_DIVIDE(SUM(quantity), COUNT(DISTINCT order_id))               AS units_per_order,
  COUNT(DISTINCT customer_id)                                        AS customers_total,
  COUNT(DISTINCT IF(is_new_customer_order,     customer_id, NULL))   AS new_customers,
  COUNT(DISTINCT IF(NOT is_new_customer_order, customer_id, NULL))   AS returning_customers,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))      AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))      AS returning_orders,
  SUM(IF(is_new_customer_order,     line_total, 0))                  AS new_revenue,
  SUM(IF(NOT is_new_customer_order, line_total, 0))                  AS returning_revenue,
  SAFE_DIVIDE(
    COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL)),
    COUNT(DISTINCT order_id))                                        AS repeat_order_rate,
  SAFE_DIVIDE(
    SUM(IF(NOT is_new_customer_order, line_total, 0)), SUM(line_total)) AS returning_revenue_share
FROM `bidbrain-analytics.client_cityperfume.stg_sales`;
