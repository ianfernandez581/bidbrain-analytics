-- City Perfume — site-wide GA4 ecommerce funnel (Website tab): sessions -> view_item ->
-- add_to_cart -> begin_checkout -> purchase. Assembled from BOTH GA4 tables: sessions
-- from the acquisition table (stg_ga4), the mid/lower-funnel event counts from the
-- event-grain table (perf_ga4_events, which has NO source dimension) — so the funnel is
-- WHOLE-SITE only, not segmentable by channel. event_name='purchase' is the canonical
-- step (is_conversion_event is unreliable across the date range). Window 2025-06-01 ->.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_funnel` AS
WITH s AS (
  SELECT SUM(sessions) AS sessions
  FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
),
ev AS (
  SELECT
    SUM(IF(event_name = 'view_item',      event_count, 0)) AS view_item,
    SUM(IF(event_name = 'add_to_cart',    event_count, 0)) AS add_to_cart,
    SUM(IF(event_name = 'begin_checkout', event_count, 0)) AS begin_checkout,
    SUM(IF(event_name = 'purchase',       event_count, 0)) AS purchase
  FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
  WHERE client_slug = 'city-perfume'
    AND metric_date >= DATE '2025-01-01'
)
SELECT
  s.sessions,
  ev.view_item,
  ev.add_to_cart,
  ev.begin_checkout,
  ev.purchase
FROM s CROSS JOIN ev;
