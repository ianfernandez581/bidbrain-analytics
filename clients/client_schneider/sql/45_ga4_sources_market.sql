-- Schneider Electric — GA4 top source/medium (whole property), capped to the 60 globally-largest
-- source/mediums. SHIPPED DISABLED (0 rows until stg_ga4's property placeholder is set). Whole-site
-- single 'All' market. Mirrors client_vmch/sql/17.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_sources_market` AS
WITH top AS (
  SELECT source_medium
  FROM `bidbrain-analytics.client_schneider.stg_ga4`
  GROUP BY source_medium
  ORDER BY SUM(sessions) DESC
  LIMIT 60
)
SELECT
  'All' AS market,
  source_medium,
  ANY_VALUE(channel_group)   AS channel,
  ANY_VALUE(channel_bucket)  AS bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
WHERE source_medium IN (SELECT source_medium FROM top)
GROUP BY source_medium;
