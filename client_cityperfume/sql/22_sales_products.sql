-- City Perfume — top products (Sales tab). Top 50 by revenue UNION top 50 by margin, so
-- the dashboard can render both a "top by revenue" and a "top by margin" list from one
-- set (rev_rank / margin_rank flag membership). Grain = product_name (more granular than
-- sku here; 23k names). Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_products` AS
WITH p AS (
  SELECT
    product_name,
    ANY_VALUE(category)                       AS category,
    SUM(line_total)                           AS revenue,
    SUM(margin)                               AS margin,
    SAFE_DIVIDE(SUM(margin), SUM(line_total)) AS margin_pct,
    SUM(quantity)                             AS units,
    COUNT(DISTINCT order_id)                  AS orders
  FROM `bidbrain-analytics.client_cityperfume.stg_sales`
  WHERE product_name IS NOT NULL AND product_name != ''
  GROUP BY product_name
),
ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (ORDER BY revenue DESC) AS rev_rank,
    ROW_NUMBER() OVER (ORDER BY margin  DESC) AS margin_rank
  FROM p
)
SELECT product_name, category, revenue, margin, margin_pct, units, orders, rev_rank, margin_rank
FROM ranked
WHERE rev_rank <= 50 OR margin_rank <= 50
ORDER BY revenue DESC;
