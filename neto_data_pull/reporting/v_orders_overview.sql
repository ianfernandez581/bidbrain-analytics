-- =============================================================================
-- v_orders_overview  —  SAMPLE reporting view (one row per order)
-- =============================================================================
-- ⚠️ THIS IS NOT PART OF THE RAW LAYER. It is a *reference* reporting view that
-- belongs in the CLIENT layer (e.g. client_cityperfume/sql/) once wired to a
-- dashboard. The raw layer (raw_neto.orders) stays a dumb mirror; all business
-- logic — identity resolution, derived history, amounts owed — lives here in the
-- client/reporting layer, exactly like the other clients' views read raw_windsor /
-- raw_snowflake. It is committed here only as a worked example of how to consume
-- raw_neto.orders.
--
-- CUSTOMER IDENTITY (design-critical):
--   The entity key is EMAIL when present. Username is NOT a reliable person key —
--   guest/POS orders share 'noreg' or scrambled system handles — so we NEVER window
--   on username. When email is null we anchor the identity on the order itself
--   ('order:' || order_id) so every no-email order is its OWN one-off identity and
--   they are not collapsed into one fake mega-customer.
--
-- NOTE on buyer_name / state / country: per the spec these come from the order's
--   Bill*/Ship* address fields. For City Perfume those fields currently arrive EMPTY
--   from the Neto API (the store/key does not expose order-level address PII — see
--   the loader README), so these columns will be blank/NULL here until that changes.
--   The expressions are correct and will populate for any store that returns them.
-- =============================================================================

WITH base AS (
  SELECT
    order_id,
    order_status,
    sales_channel,
    purchase_order_number,
    default_payment_type,
    tax_inclusive,
    date_placed,
    bill_first_name,
    bill_last_name,
    -- delivery location: prefer shipping, fall back to billing (both empty today)
    COALESCE(NULLIF(ship_state, ''),   NULLIF(bill_state, ''))   AS state,
    COALESCE(NULLIF(ship_country, ''), NULLIF(bill_country, '')) AS country,
    product_subtotal,
    shipping_total,
    surcharge_total,
    grand_total,
    NULLIF(email, '') AS email,
    order_lines,
    -- identity key: email when present, else this order on its own
    COALESCE(NULLIF(email, ''), CONCAT('order:', order_id)) AS customer_id,
    -- amount actually received for THIS order (sum of its nested payments)
    (SELECT SUM(op.amount) FROM UNNEST(order_payments) AS op) AS amount_received
  FROM `bidbrain-analytics.raw_neto.orders`
)
SELECT
  date_placed                                              AS order_date,
  -- buyer name from billing address (empty for City Perfume today — see header)
  NULLIF(TRIM(CONCAT(COALESCE(bill_first_name, ''), ' ',
                     COALESCE(bill_last_name, ''))), '')   AS buyer_name,
  order_id,
  order_status,
  purchase_order_number,
  sales_channel,
  state,
  country,
  default_payment_type                                     AS pay_method,
  tax_inclusive,
  product_subtotal                                         AS total_product,
  shipping_total                                           AS total_shipping,
  surcharge_total                                          AS total_surcharge,
  grand_total,
  email,
  customer_id,
  order_lines,                                             -- nested line items, carried through
  amount_received,
  grand_total - COALESCE(amount_received, 0)               AS amount_owed,

  -- ---- derived over the customer's order history (windowed on EMAIL identity) ----
  -- one row per order_id, so COUNT(*) OVER == number of that customer's orders.
  MAX(date_placed) OVER (PARTITION BY customer_id)         AS last_order_date,
  COUNT(*)         OVER (PARTITION BY customer_id)         AS total_orders,
  -- orders placed by this customer in the current (store-local) calendar year
  SUM(IF(EXTRACT(YEAR FROM date_placed)
         = EXTRACT(YEAR FROM CURRENT_DATE('Australia/Sydney')), 1, 0))
      OVER (PARTITION BY customer_id)                      AS order_ytd
FROM base
