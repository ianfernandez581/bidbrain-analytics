-- City Perfume — top products per DAY (range-aware source for the products table).
-- Ships a POOL — every product in the full-period top 80 by revenue OR top 80 by margin — at
-- day grain, so the dashboard clips to the range, re-aggregates per product, and re-ranks to the
-- top 50 over the selected window. Day rows are sparse (a product only appears on days it sold),
-- so this stays compact. APPROXIMATION: a product tiny over the whole window but big within a
-- short sub-range could fall outside the 80/80 pool. Additive columns only. Aggregates only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.sales_products_daily` AS
WITH pool AS (
  SELECT product_name FROM (
    SELECT
      product_name,
      ROW_NUMBER() OVER (ORDER BY SUM(line_total) DESC) AS rev_rank,
      ROW_NUMBER() OVER (ORDER BY SUM(margin)     DESC) AS margin_rank
    FROM `bidbrain-analytics.client_cityperfume.stg_sales`
    WHERE product_name IS NOT NULL AND product_name != ''
    GROUP BY product_name
  )
  WHERE rev_rank <= 80 OR margin_rank <= 80
)
SELECT
  order_date                AS day,
  product_name,
  channel_group,            -- carried so the global sales-channel filter can scope top products
  ANY_VALUE(category)       AS category,
  SUM(line_total)           AS revenue,
  SUM(margin)               AS margin,
  SUM(quantity)             AS units,
  COUNT(DISTINCT order_id)  AS orders
FROM `bidbrain-analytics.client_cityperfume.stg_sales`
WHERE product_name IN (SELECT product_name FROM pool)
GROUP BY day, product_name, channel_group
ORDER BY day, revenue DESC;
