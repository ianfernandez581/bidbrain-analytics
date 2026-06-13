-- City Perfume — sales by concentration category (Sales tab). Category derived by regex on
-- product_name in stg_sales (EDP / EDT / Parfum-Other / Gift Set & Hamper / Other).
-- Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_category` AS
SELECT
  category,
  SUM(line_total)                                        AS revenue,
  SUM(margin)                                            AS margin,
  SAFE_DIVIDE(SUM(margin), SUM(line_total))              AS margin_pct,
  COUNT(DISTINCT order_id)                               AS orders,
  SUM(quantity)                                          AS units,
  SAFE_DIVIDE(SUM(line_total), COUNT(DISTINCT order_id)) AS aov
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
GROUP BY category
ORDER BY revenue DESC;
