-- ResetData — GA4 key events by event_name × DAY (the day-grain analogue of ga4_key_events).
--
-- Same source + filter as ga4_key_events (the event-grained stg_ga4_events), but keyed by
-- calendar day so the Overview "What the key events are" breakdown supports the View-by → Day
-- grain. Drops the same high-volume pageview-class events so the breakdown reads as "demand",
-- not traffic. is_conversion_event carried so the frontend can flag GA4-configured conversions.
-- raw_ga4.perf_ga4_events is already day-grained, so this is real per-day data. Volumes modest.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga4_key_events_daily` AS
SELECT
  metric_date                        AS day,
  event_name,
  LOGICAL_OR(is_conversion_event)    AS is_conversion_event,
  SUM(event_count)                   AS event_count,
  SUM(conversions)                   AS conversions,
  SUM(event_value)                   AS event_value
FROM `bidbrain-analytics.client_resetdata.stg_ga4_events`
WHERE event_name NOT IN ('page_view','session_start','first_visit','user_engagement','scroll','click')
GROUP BY day, event_name
ORDER BY day, event_count DESC;
