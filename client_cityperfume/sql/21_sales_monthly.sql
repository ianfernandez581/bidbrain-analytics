-- City Perfume — monthly sales trend (Sales tab): revenue/margin/AOV/orders + the new-vs-
-- returning split per month. All AUD, aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_monthly` AS
SELECT
  DATE_TRUNC(order_date, MONTH)                                      AS month,
  SUM(line_total)                                                    AS revenue_total,
  SUM(IF(channel_group != 'In-store POS', line_total, 0))            AS revenue_online,
  SUM(margin)                                                        AS margin,
  SAFE_DIVIDE(SUM(margin), SUM(line_total))                          AS margin_pct,
  COUNT(DISTINCT order_id)                                           AS orders,
  SAFE_DIVIDE(SUM(line_total), COUNT(DISTINCT order_id))             AS aov,
  SUM(quantity)                                                      AS units,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))      AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))      AS returning_orders,
  SUM(IF(is_new_customer_order,     line_total, 0))                  AS new_revenue,
  SUM(IF(NOT is_new_customer_order, line_total, 0))                  AS returning_revenue,
  COUNT(DISTINCT IF(is_new_customer_order,     customer_id, NULL))   AS new_customers,
  COUNT(DISTINCT IF(NOT is_new_customer_order, customer_id, NULL))   AS returning_customers
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY month
ORDER BY month;
