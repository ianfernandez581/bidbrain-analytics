-- VMCH — GA4 enquiry key events by type × month (campaign window).
--
-- IMPORTANT: GA4 `conversions` (key-event marking) is **0 for VMCH across the 2026 flight** — the
-- key-event tagging lapsed after Jan-2026 (raw_ga4 conversions: 2025-08=4,289 … 2026-01=137 …
-- 2026-02+ =0). The real enquiry signal lives in `event_count`, NOT `conversions`. So this view
-- counts the genuine enquiry ACTIONS — phone-call & email clicks, contact & call-back form submits,
-- property/sales-alert submits — from `event_count`, bucketed into clean categories by `event_name`.
-- Excluded: pure engagement (page_view / scroll / session_start / user_engagement / click),
-- downloads, donations, newsletter subscribes, and form *starts* (intent, not a completed enquiry).
--
-- Taxonomy note: GA4 renamed these events over time (2025 'Phone_call_event'/'email_event'/'Contact
-- Us Form' → 2026 'Clicked to Call'/'Clicked to Email'/'Contact Us Form - Send'); the regexes match
-- both vintages, so older months still count when the dashboard date range is expanded.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_key_events` AS
SELECT
  FORMAT_DATE('%Y-%m', metric_date) AS month,
  category                          AS event_name,
  SUM(event_count)                  AS key_events
FROM (
  SELECT
    metric_date,
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
  WHERE metric_date >= DATE '2025-01-01'
)
WHERE category IS NOT NULL
GROUP BY month, category
ORDER BY month, key_events DESC;
