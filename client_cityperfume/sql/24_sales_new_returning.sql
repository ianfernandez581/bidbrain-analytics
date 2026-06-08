-- City Perfume — new vs returning customers, monthly (Sales tab — surfaced prominently).
-- An order is "new" if it is the customer's FIRST-EVER order (computed over full history
-- in stg_sales, then windowed); "returning" otherwise. Customer counts use customer_id
-- as the identity key (100% populated; email is 35% null). Aggregates only — no ids leave.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_new_returning` AS
SELECT
  DATE_TRUNC(order_date, MONTH)                                      AS month,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))      AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))      AS returning_orders,
  SUM(IF(is_new_customer_order,     line_total, 0))                  AS new_revenue,
  SUM(IF(NOT is_new_customer_order, line_total, 0))                  AS returning_revenue,
  COUNT(DISTINCT IF(is_new_customer_order,     customer_id, NULL))   AS new_customers,
  COUNT(DISTINCT IF(NOT is_new_customer_order, customer_id, NULL))   AS returning_customers,
  SAFE_DIVIDE(
    COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL)),
    COUNT(DISTINCT order_id))                                        AS returning_order_share,
  SAFE_DIVIDE(
    SUM(IF(NOT is_new_customer_order, line_total, 0)), SUM(line_total)) AS returning_revenue_share
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY month
ORDER BY month;
