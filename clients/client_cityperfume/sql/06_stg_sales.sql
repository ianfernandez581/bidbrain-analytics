-- City Perfume — first-party SALES staging (the source of truth). Filter/clean once here.
--
-- Source: bidbrain-analytics.client_cityperfume.v_sales (order-line grain, 358,695 lines).
-- This is the ground truth for revenue / margin / orders / AOV / customers — the blended
-- ROAS denominator. AUD (no currency column; AU business). Window 2025-01-01 -> latest.
--
-- PRIVACY: customer_id is carried here ONLY to compute the new-vs-returning flag and the
-- distinct-customer counts inside BigQuery. It (and email) MUST NEVER be selected by any
-- roll-up the export job reads, and MUST NEVER reach cityperfume.json. The 20..24 sales
-- roll-ups emit aggregates only. email is dropped entirely (it is also 35% null; customer_id
-- is the identity key).
--
-- NEW vs RETURNING: computed over the customer's FULL order history (not just the window) —
-- an order is "new-customer" only if it is that customer's first-ever order. We therefore
-- rank every order across all history, then keep only window rows. (Windowing before
-- ranking would mislabel a 2023-acquired customer's 2025 order as "new".)
--
-- channel_group folds the 20 sales_channel values into In-store POS / Website / Marketplace
-- / Other (the long tail of junk/zero channels). category is a CONCENTRATION class derived
-- by regex on product_name (75%+ carry a size token; ~0 nulls). Margin is net-as-reported
-- and has known data-quality noise (zero-cost-price lines inflate it; promo lines go
-- negative) — surfaced honestly with a dashboard caveat, not silently scrubbed.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_sales` AS
WITH order_level AS (
  SELECT
    order_id,
    ANY_VALUE(customer_id) AS customer_id,
    MIN(date_placed)       AS order_ts
  FROM `bidbrain-analytics.client_cityperfume.v_sales`
  GROUP BY order_id
),
order_seq AS (
  SELECT
    order_id,
    customer_id,
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_ts, order_id) AS order_seq
  FROM order_level
)
SELECT
  s.order_id,
  DATE(s.date_placed)               AS order_date,
  s.sales_channel,
  CASE
    WHEN s.sales_channel = 'Neto POS'                          THEN 'In-store POS'
    WHEN s.sales_channel IN ('Website', 'API')                 THEN 'Website'
    WHEN s.sales_channel IN (
      'BigW', 'Lasoo', 'OzSale', 'eBay', 'Amazon AU', 'MyDeal',
      'EverydayMarket', 'Catch', 'Kogan', 'Stockland', 'Mosaic'
    )                                                          THEN 'Marketplace'
    ELSE 'Other'
  END                               AS channel_group,
  CASE
    WHEN REGEXP_CONTAINS(LOWER(s.product_name), r'hamper|gift set|gift pack|gift box') THEN 'Gift Set & Hamper'
    WHEN REGEXP_CONTAINS(LOWER(s.product_name), r'\bedp\b|eau de parfum')              THEN 'EDP'
    WHEN REGEXP_CONTAINS(LOWER(s.product_name), r'\bedt\b|eau de toilette')            THEN 'EDT'
    WHEN REGEXP_CONTAINS(LOWER(s.product_name), r'parfum|elixir|extrait|cologne|\bedc\b') THEN 'Parfum/Other'
    ELSE 'Other'
  END                               AS category,
  s.product_name,
  s.sku,
  s.quantity,
  s.unit_price,
  s.line_total,
  s.cost_price,
  s.margin,
  seq.customer_id,                              -- BQ-INTERNAL ONLY — never exported
  (seq.order_seq = 1)               AS is_new_customer_order
FROM `bidbrain-analytics.client_cityperfume.v_sales` s
JOIN order_seq seq USING (order_id)
WHERE DATE(s.date_placed) >= DATE '2025-01-01';
