-- VMCH — GA4 enquiry key events by type × day (campaign window). Mirrors 06_ga4_key_events.sql
-- at metric_date grain so the "Enquiry events by type" chart can offer a Day view.
-- See 06_ga4_key_events.sql for the full taxonomy notes (the real enquiry signal is `event_count`,
-- NOT `conversions`, which lapsed to 0 across the 2026 flight). Same regex buckets, daily grain.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_key_events_daily` AS
SELECT
  day,
  category AS event_name,
  SUM(event_count) AS key_events
FROM (
  SELECT
    metric_date AS day,
    event_count,
    CASE
      WHEN REGEXP_CONTAINS(LOWER(event_name), r'call.?back|book a call|hcp call back') THEN 'Call-back request'
      WHEN REGEXP_CONTAINS(LOWER(event_name), r'call|phone')                           THEN 'Phone call'
      WHEN REGEXP_CONTAINS(LOWER(event_name), r'mail|email')                           THEN 'Email enquiry'
      WHEN REGEXP_CONTAINS(LOWER(event_name), r'contact')
           AND NOT REGEXP_CONTAINS(LOWER(event_name), r'start')                        THEN 'Contact form'
      WHEN REGEXP_CONTAINS(LOWER(event_name), r'property alert|sales alert')
           AND NOT REGEXP_CONTAINS(LOWER(event_name), r'start')                        THEN 'Property/sales alert'
      ELSE NULL
    END AS category
  FROM `bidbrain-analytics.client_vmch.stg_ga4_events`
  WHERE metric_date >= DATE '2026-04-01'
)
WHERE category IS NOT NULL
GROUP BY day, category
ORDER BY day, key_events DESC;
