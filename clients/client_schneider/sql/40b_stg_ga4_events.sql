-- Schneider Electric — staged GA4 event-grain base (top website events). SHIPPED DISABLED (0 rows
-- until the SE GA4 property id is set). Mirrors client_vmch/sql/02_stg_ga4_events.sql.
--
-- Source: raw_ga4.perf_ga4_events (property × day × event_name). The DTS Events report exposes
-- event_count but NOT the per-event key-event flag, so `key_events` (= conversions) is NULL from DTS;
-- the headline key-events total comes from stg_ga4.conversions instead. The `Sessions` pseudo-event
-- (a loader artifact mirroring session counts) is dropped.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_ga4_events` AS
SELECT
  metric_date,
  event_name,
  CAST(event_count AS INT64)   AS event_count,
  CAST(conversions AS NUMERIC) AS key_events
FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
WHERE property_id IN ('REPLACE_WITH_SE_GA4_PROPERTY_ID')   -- <<< placeholder: matches no rows until set
  AND event_name != 'Sessions';
