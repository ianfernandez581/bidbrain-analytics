-- ResetData — staged GA4 key events (the demand-gen / lead events, by name).
--
-- stg_ga4 collapses every key event into a single `conversions` total; this view keeps the
-- per-EVENT_NAME split so the Website tab can show WHICH events fired (Leadform_submit /
-- sign_up / start_$50_free_credit_click / file_download / learn_more_click / form_start …).
-- Plain filter on raw_ga4.perf_ga4_events, client_slug = 'reset-data'.
--
-- is_conversion_event flags GA4-configured conversions (today only Leadform_submit), so the
-- dashboard can separate "configured conversions" from broader engagement events. Volumes are
-- modest (B2B, low traffic) — surfaced honestly, never inflated. event_value is mostly 0.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_ga4_events` AS
SELECT
  metric_date,
  event_name,
  is_conversion_event,
  event_count,
  event_value,
  conversions
FROM `bidbrain-analytics.raw_ga4.perf_ga4_events`
WHERE client_slug = 'reset-data';
