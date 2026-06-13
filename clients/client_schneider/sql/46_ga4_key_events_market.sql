-- Schneider Electric — GA4 key events BY event name × month × market. SHIPPED DISABLED.
-- Reads the raw event-grained source directly (so the per-event-type split survives), with the
-- SAME property placeholder as stg_ga4 → 0 rows until set. The EVENT_NAME = LOWER(EVENT_NAME)
-- guard drops the feed's capitalised 'Sessions' pseudo-metric row. Mirrors client_STT/sql/06.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_key_events_market` AS
SELECT
  FORMAT_DATE('%Y-%m', DATE(DAY))                  AS month,
  COALESCE(NULLIF(COUNTRY_NAME, ''), '(not set)')  AS market,
  EVENT_NAME                                       AS event_name,
  SUM(KEY_EVENTS)                                  AS key_events
FROM `bidbrain-analytics.raw_snowflake.google_analytics_apac_all`
WHERE PROPERTY_ID IN ('REPLACE_WITH_SE_GA4_PROPERTY_IDS')   -- <<< placeholder: matches no rows until set
  AND KEY_EVENTS > 0
  AND EVENT_NAME = LOWER(EVENT_NAME)
  AND DATE(DAY) >= DATE '2025-01-01'
GROUP BY month, market, event_name
ORDER BY month, market, key_events DESC;
