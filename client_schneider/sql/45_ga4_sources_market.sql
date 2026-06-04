-- Schneider Electric — GA4 top source/medium BY market (campaign window), capped to the 60
-- globally-largest source/mediums. SHIPPED DISABLED (0 rows until stg_ga4's property placeholder
-- is set). Mirrors client_STT/sql/17.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ga4_sources_market` AS
WITH top AS (
  SELECT session_source_medium
  FROM `bidbrain-analytics.client_schneider.stg_ga4`
  WHERE metric_date >= DATE '2025-06-01'
  GROUP BY session_source_medium
  ORDER BY SUM(sessions) DESC
  LIMIT 60
)
SELECT
  market,
  session_source_medium      AS source_medium,
  ANY_VALUE(channel_group)   AS channel,
  ANY_VALUE(channel_bucket)  AS bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_schneider.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
  AND session_source_medium IN (SELECT session_source_medium FROM top)
GROUP BY market, source_medium;
