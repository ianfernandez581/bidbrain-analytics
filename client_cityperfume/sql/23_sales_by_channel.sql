-- City Perfume — sales by channel (Sales tab). One row per raw sales_channel with its
-- coarse channel_group (In-store POS / Website / Marketplace / Other), so the dashboard
-- can show both the grouped split and the channel detail. Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_by_channel` AS
SELECT
  sales_channel,
  ANY_VALUE(channel_group)                                          AS channel_group,
  SUM(line_total)                                                   AS revenue,
  SUM(margin)                                                       AS margin,
  SAFE_DIVIDE(SUM(margin), SUM(line_total))                         AS margin_pct,
  COUNT(DISTINCT order_id)                                          AS orders,
  SAFE_DIVIDE(SUM(line_total), COUNT(DISTINCT order_id))            AS aov,
  SUM(quantity)                                                     AS units,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))     AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))     AS returning_orders
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY sales_channel
ORDER BY revenue DESC;
