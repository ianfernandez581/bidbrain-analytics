-- =============================================================================
-- v_sales  —  SAMPLE reporting view (one row per SKU per order; product grain)
-- =============================================================================
-- ⚠️ NOT PART OF THE RAW LAYER. Like v_orders_overview.sql this is a *reference*
-- client/reporting view (belongs in e.g. client_cityperfume/sql/ when wired to a
-- dashboard). raw_neto.orders keeps order_lines as the typed REPEATED RECORD; this
-- view just FLATTENS it with UNNEST into the product-grain "sales" dataset the
-- dashboard needs (top products, revenue by SKU, units sold, basket size).
--
-- DISCOUNTS: Neto's per-line `product_discount` is the dollar discount already
--   applied to the line (e.g. unit_price 300 × qty 1, product_discount 30 → 270),
--   so line_total = quantity × unit_price − product_discount. `percent_discount`
--   is the informational % and is intentionally not re-applied (it would double-count).
-- MARGIN is gross: line_total − quantity × cost_price (cost_price is ex-tax landed
--   cost from Neto). It does not net out order-level coupons or shipping.
-- IDENTITY: same email-first rule as v_orders_overview (email, else 'order:'||order_id),
--   so no-email orders are their own identity and never collapsed together.
-- =============================================================================

SELECT
  o.order_id,
  o.date_placed,
  o.sales_channel,
  NULLIF(o.email, '')                                      AS email,
  COALESCE(NULLIF(o.email, ''), CONCAT('order:', o.order_id)) AS customer_id,
  ol.sku,
  ol.product_name,
  ol.quantity,
  ol.unit_price,
  -- net line revenue: gross less the per-line dollar discount
  ol.quantity * ol.unit_price - COALESCE(ol.product_discount, 0)            AS line_total,
  ol.cost_price,
  -- gross margin on the line: net revenue less landed cost of the units
  (ol.quantity * ol.unit_price - COALESCE(ol.product_discount, 0))
      - ol.quantity * COALESCE(ol.cost_price, 0)                            AS margin
FROM `bidbrain-analytics.raw_neto.orders` AS o,
     UNNEST(o.order_lines) AS ol
