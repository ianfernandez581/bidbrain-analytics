-- Schneider Electric — top website events by count × month (whole property). SHIPPED DISABLED (0 rows
-- until stg_ga4_events' property placeholder is set). Reads stg_ga4_events.
--
-- NOTE: GA4's DTS Events report exposes event_count but NOT which events are "key events", so this is
-- TOP EVENTS BY VOLUME (event_count), not conversions. The headline Key-events KPI uses the session-
-- grain keyEvents metric (ga4_kpi_market.conversions), which IS populated. Once Schneider confirm which
-- event names count as conversions, filter the WHERE to those names to make this a true key-events view.
-- Pure-engagement events (page views / scroll / session_start / etc.) are excluded as noise.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_key_events_market` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date) AS month,
  'All' AS market,
  event_name,
  SUM(event_count) AS key_events
FROM `bidbrain-analytics.client_schneider.stg_ga4_events`
WHERE event_name NOT IN ('session_start','first_visit','user_engagement','scroll','page_view','form_start')
GROUP BY month, event_name
ORDER BY month, key_events DESC;
