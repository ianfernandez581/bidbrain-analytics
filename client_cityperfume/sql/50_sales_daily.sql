-- City Perfume — first-party sales per DAY (the range-aware spine of the Sales/Overview tabs).
-- Day grain so the dashboard clips to the exact selected date range and aggregates up (and
-- buckets to day/week/month for trend charts by range span). Additive columns only; the
-- dashboard derives margin_pct / aov / repeat-rate / shares from the summed columns.
-- NOTE on customers: new_customers is EXACT when summed over any range (a customer is "new"
-- on exactly one day — their first-ever order); returning_customers over-counts across days
-- (shown as ≈ in the UI). Aggregates only — no customer_id/email ever leaves here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_daily` AS
SELECT
  order_date                                                         AS day,
  SUM(line_total)                                                    AS revenue_total,
  SUM(IF(channel_group != 'In-store POS', line_total, 0))            AS revenue_online,
  SUM(margin)                                                        AS margin,
  COUNT(DISTINCT order_id)                                           AS orders,
  SUM(quantity)                                                      AS units,
  COUNT(DISTINCT IF(is_new_customer_order,     order_id, NULL))      AS new_orders,
  COUNT(DISTINCT IF(NOT is_new_customer_order, order_id, NULL))      AS returning_orders,
  SUM(IF(is_new_customer_order,     line_total, 0))                  AS new_revenue,
  SUM(IF(NOT is_new_customer_order, line_total, 0))                  AS returning_revenue,
  COUNT(DISTINCT IF(is_new_customer_order,     customer_id, NULL))   AS new_customers,
  COUNT(DISTINCT IF(NOT is_new_customer_order, customer_id, NULL))   AS returning_customers
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY day
ORDER BY day;
