-- City Perfume — site-wide GA4 ecommerce funnel per DAY (range-aware source for the funnel).
-- Sessions from the acquisition table (stg_ga4); the mid/lower-funnel event counts from the
-- event-grain table (perf_ga4_events, no source dimension) — whole-site only. All steps are
-- additive session/event counts, so the dashboard sums the days in range. FULL OUTER JOIN on
-- day so a day present in one table but not the other still appears. Window 2025-01-01 ->.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_funnel_daily` AS
WITH s AS (
  SELECT metric_date AS day, SUM(sessions) AS sessions
  FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
  GROUP BY day
),
ev AS (
  SELECT
    metric_date                                           AS day,
    SUM(IF(event_name = 'view_item',      event_count, 0)) AS view_item,
    SUM(IF(event_name = 'add_to_cart',    event_count, 0)) AS add_to_cart,
    SUM(IF(event_name = 'begin_checkout', event_count, 0)) AS begin_checkout,
    SUM(IF(event_name = 'purchase',       event_count, 0)) AS purchase
  FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
  WHERE client_slug = 'city-perfume'
    AND metric_date >= DATE '2025-01-01'
  GROUP BY day
)
SELECT
  day,
  COALESCE(s.sessions, 0)        AS sessions,
  COALESCE(ev.view_item, 0)      AS view_item,
  COALESCE(ev.add_to_cart, 0)    AS add_to_cart,
  COALESCE(ev.begin_checkout, 0) AS begin_checkout,
  COALESCE(ev.purchase, 0)       AS purchase
FROM s
FULL OUTER JOIN ev USING (day)
ORDER BY day;
