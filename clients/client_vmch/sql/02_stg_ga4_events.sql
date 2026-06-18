-- VMCH — staged GA4 event-grain base (for key events by type), with a DTS→Windsor fallback.
--
-- One row per (property × metric_date × event_name), carrying event_count and conversions
-- (= key-event count). The `Sessions` pseudo-event (a loader artifact mirroring session
-- counts, NOT a real key event) is excluded. No geo/market dimension — VMCH is AU-only.
--
-- TWO SOURCES, PER-DATE PRECEDENCE (added 2026-06-18) — same pattern as 01_stg_ga4.sql:
--   * PRIMARY  = native GA4 Data Transfer (`raw_ga4.perf_ga4_events`, slug vmch-website-ga4).
--   * FALLBACK = Windsor GA4 connector (`raw_windsor.perf_ga4_events`, property 287370621).
-- DTS wins on any date it has; Windsor fills only the missing dates (the gap), so events are
-- never double-counted. The two sources share an identical event-name vocabulary (verified),
-- so 06_ga4_key_events.sql's regex bucketing works the same for either.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ga4_events` AS
WITH src AS (
  SELECT metric_date, event_name,
         CAST(event_count AS INT64) AS event_count,
         CAST(conversions AS NUMERIC) AS key_events,
         'dts' AS _src
  FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
  WHERE client_slug = 'vmch-website-ga4'
  UNION ALL
  SELECT metric_date, event_name,
         CAST(event_count AS INT64),
         CAST(conversions AS NUMERIC),
         'windsor' AS _src
  FROM `bidbrain-analytics.raw_windsor.perf_ga4_events`
  WHERE property_id = '287370621'
),
dts_dates AS (SELECT DISTINCT metric_date FROM src WHERE _src = 'dts')
SELECT metric_date, event_name, event_count, key_events
FROM src
WHERE (_src = 'dts' OR metric_date NOT IN (SELECT metric_date FROM dts_dates))
  AND event_name != 'Sessions';
