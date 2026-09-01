-- 12_stg_ga4_events: the Geocon slice of raw_windsor.perf_ga4_events (GA4 event counts,
-- property x date x event_name). Added 2026-08-31 with 11_stg_ga4 - see that header for the
-- property ids, the naming caveat and the Windsor-not-DTS reasoning.
--
-- Events carry NO campaign dimension, so they can only ever be SITE-level - there is no
-- development attribution here and the dashboard must not imply one.
--
-- What the feed actually holds today (2026-08-31): standard GA4 auto events only. The landing
-- site reports 63 form_start and ZERO form_submit, and NO event is flagged is_conversion_event -
-- web enquiry tracking is thin, and the dashboard says so rather than presenting form starts as
-- enquiries.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_ga4_events` AS
SELECT
  metric_date                                AS date,
  property_id,
  CASE property_id
    WHEN '550962241' THEN 'Geocon brand site'
    WHEN '551838402' THEN 'Gateway Braddon site'
    ELSE property_id
  END                                        AS site,
  event_name,
  is_conversion_event,
  event_count
FROM `bidbrain-analytics.raw_windsor.perf_ga4_events`
WHERE property_id IN ('550962241', '551838402')
