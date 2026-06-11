-- City Perfume — sales by concentration category per DAY (range-aware source for the Sales-tab
-- category chart). category derived by regex on product_name in stg_sales. Day grain; the
-- dashboard clips + re-aggregates per category and derives margin_pct. Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_category_daily` AS
SELECT
  order_date                AS day,
  category,
  SUM(line_total)           AS revenue,
  SUM(margin)               AS margin,
  COUNT(DISTINCT order_id)  AS orders,
  SUM(quantity)             AS units
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY day, category
ORDER BY day, revenue DESC;
