-- ResetData — GA4 key events by event_name × month (the demand-gen / lead signal).
--
-- Goes to the event-grained stg_ga4_events (NOT stg_ga4, which has already collapsed events
-- into a single `conversions`) so the dashboard can show WHICH events fired month by month
-- (Leadform_submit / sign_up / start_$50_free_credit_click / file_download / learn_more_click …).
-- is_conversion_event is carried so the frontend can flag GA4-configured conversions
-- (today only Leadform_submit) vs broader engagement events. Volumes are modest — shown as-is.
-- Drops the high-volume non-key pageview-class events so the breakdown reads as "demand", not traffic.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga4_key_events` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date)  AS month,
  event_name,
  LOGICAL_OR(is_conversion_event)    AS is_conversion_event,
  SUM(event_count)                   AS event_count,
  SUM(conversions)                   AS conversions,
  SUM(event_value)                   AS event_value
FROM `bidbrain-analytics.client_resetdata.stg_ga4_events`
WHERE event_name NOT IN ('page_view','session_start','first_visit','user_engagement','scroll','click')
GROUP BY month, event_name
ORDER BY month, event_count DESC;
