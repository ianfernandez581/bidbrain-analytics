-- VMCH — staged GA4 event-grain base (for key events by type).
--
-- Source raw_ga4.perf_ga4_events has one row per (property_id × metric_date × event_name).
-- This carries event_count and conversions (key event count).
-- The `Sessions` pseudo-event (a Windsor loader artifact that mirrors session counts
-- and is NOT a real key event) is excluded per the intake spec.
-- No geo/market dimension — VMCH is AU-only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ga4_events` AS
SELECT
  metric_date,
  event_name,
  event_count,
  CAST(conversions AS NUMERIC) AS key_events
FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
WHERE client_slug = 'vmch-website-ga4'
  AND event_name != 'Sessions';