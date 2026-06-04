-- STT GDC — GA4 key events broken down BY event name, BY month, BY market.
-- The rest of the GA4 views collapse every key event into a single `conversions`
-- total at stg_ga4 (01_stg_ga4.sql) — EVENT_NAME is gone by then. This view goes
-- back to the raw event-grained source to KEEP the per-type split, so the dashboard
-- can show which key events fired (contact / lead / newsletter / …) month by month.
--
-- "All key events" = any EVENT_NAME GA4 counts as a key event (KEY_EVENTS > 0), NOT
-- the fixed contact/lead/newsletter allowlist stg_ga4 sums into `conversions` — so a
-- newly-configured GA4 key event shows up here automatically (e.g. file_download,
-- which the stg_ga4 allowlist misses). Same property filter, market mapping and
-- 2025-01 floor as the other ga4_*_market views, so the dashboard sums it over the
-- selected countries exactly like ga4_monthly_market.
--
-- The EVENT_NAME = LOWER(EVENT_NAME) guard drops the Snowflake feed's pseudo-metric
-- rows: it emits a capitalised 'Sessions' row whose KEY_EVENTS just mirrors
-- EVENT_COUNT (~659k), which is NOT a key event. Real GA4 events are lowercase
-- snake_case — this is exactly why stg_ga4 hand-picks names instead of trusting
-- KEY_EVENTS blindly.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_key_events_market` AS
SELECT
  FORMAT_DATE('%Y-%m', DATE(DAY))                  AS month,
  COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')  AS market,
  EVENT_NAME                                       AS event_name,
  SUM(KEY_EVENTS)                                  AS key_events
FROM `bidbrain-analytics.raw_snowflake.google_analytics_apac_all`
WHERE PROPERTY_ID = '318963196'
  AND KEY_EVENTS > 0
  AND EVENT_NAME = LOWER(EVENT_NAME)
  AND DATE(DAY) >= DATE '2025-01-01'
GROUP BY month, market, event_name
ORDER BY month, market, key_events DESC;
