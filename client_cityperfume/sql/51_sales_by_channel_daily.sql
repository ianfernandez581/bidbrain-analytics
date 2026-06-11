-- City Perfume — sales by channel per DAY (range-aware source for the channel donut + table).
-- Day grain; the dashboard clips to the range and re-aggregates per channel, deriving
-- aov / margin_pct / returning-share from the summed columns. Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_by_channel_daily` AS
SELECT
  order_date                                                       AS day,
  sales_channel,
  ANY_VALUE(channel_group)                                        AS channel_group,
  SUM(line_total)                                                 AS revenue,
  SUM(margin)                                                     AS margin,
  COUNT(DISTINCT order_id)                                        AS orders,
  SUM(quantity)                                                   AS units,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))   AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))   AS returning_orders
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY day, sales_channel
ORDER BY day, revenue DESC;
