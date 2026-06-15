-- STT GDC — GA4 key events by event name × DAY × market. Day-grain mirror of
-- ga4_key_events_market (06): powers the Website tab's key-events chart under
-- "VIEW BY → Day". Goes back to the raw event-grained source (same as 06) to KEEP
-- the per-type split that stg_ga4 collapses into a single `conversions` total.
--
-- Same PROPERTY_ID filter, KEY_EVENTS > 0 / lowercase-EVENT_NAME guards and market
-- mapping as 06, so the dashboard's day branch sums it over the selected countries
-- exactly like the month branch reads ga4_key_events_market. From 2025-06-01 to
-- bound the day list (day grain is only meaningful in the active flight).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_key_events_daily_market` AS
SELECT
  DATE(DAY)                                        AS day,
  COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')  AS market,
  EVENT_NAME                                       AS event_name,
  SUM(KEY_EVENTS)                                  AS key_events
FROM `bidbrain-analytics.raw_snowflake.google_analytics_apac_all`
WHERE PROPERTY_ID = '318963196'
  AND KEY_EVENTS > 0
  AND EVENT_NAME = LOWER(EVENT_NAME)
  AND DATE(DAY) >= DATE '2025-06-01'
GROUP BY day, market, event_name
ORDER BY day, market, key_events DESC;
