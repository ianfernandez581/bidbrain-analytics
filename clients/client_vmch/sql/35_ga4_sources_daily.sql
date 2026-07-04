-- VMCH — GA4 top source/medium, PER DAY.
-- Daily twin of 17_ga4_sources_market so the Website sources table responds to the
-- date-range picker. Restricted to the flight top-40 source_mediums (bounds payload;
-- the frontend re-aggregates within range then shows the top 15 — any sub-range's
-- top 15 sits comfortably inside the flight top 40).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_sources_daily` AS
WITH top AS (
  SELECT source_medium
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY source_medium
  ORDER BY SUM(sessions) DESC
  LIMIT 40
)
SELECT
  metric_date               AS day,
  source_medium,
  ANY_VALUE(channel_group)  AS channel,
  ANY_VALUE(channel_bucket) AS bucket,
  SUM(sessions)             AS sessions,
  SUM(engaged_sessions)     AS engaged,
  SUM(conversions)          AS conversions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
  AND source_medium IN (SELECT source_medium FROM top)
GROUP BY metric_date, source_medium;
