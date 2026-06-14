-- VMCH — GA4 top source/medium. Single "Australia" market.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ga4_sources_market` AS
WITH top AS (
  SELECT source_medium
  FROM `bidbrain-analytics.client_vmch.stg_ga4`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY source_medium
  ORDER BY SUM(sessions) DESC
  LIMIT 60
)
SELECT
  'Australia' AS market,
  source_medium,
  ANY_VALUE(channel_group)  AS channel,
  ANY_VALUE(channel_bucket) AS bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_vmch.stg_ga4`
WHERE metric_date >= DATE '2026-04-01'
  AND source_medium IN (SELECT source_medium FROM top)
GROUP BY source_medium;