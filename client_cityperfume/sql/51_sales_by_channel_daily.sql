-- City Perfume — sales by channel per DAY (range-aware source for the channel donut + table
-- AND the GLOBAL sales-channel filter). Day grain; the dashboard clips to the range, filters to
-- the selected channel_group(s), and re-aggregates — deriving aov / margin_pct / returning-share
-- from the summed columns. This is the single channel-grained sales source: it carries the same
-- measures as sales_daily (incl. new/returning revenue & customers) so the dashboard can rebuild
-- every sales KPI/trend for any channel subset. Aggregates only.
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
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))   AS returning_orders,
  SUM(IF(is_new_customer_order,     line_total, 0))               AS new_revenue,
  SUM(IF(NOT is_new_customer_order, line_total, 0))               AS returning_revenue,
  COUNT(DISTINCT IF(is_new_customer_order,     customer_id, NULL)) AS new_customers,
  COUNT(DISTINCT IF(NOT is_new_customer_order, customer_id, NULL)) AS returning_customers
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY day, sales_channel
ORDER BY day, revenue DESC;
