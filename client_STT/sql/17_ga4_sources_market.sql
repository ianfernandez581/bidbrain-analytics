-- STT GDC — GA4 top source/medium BY market (campaign window).
-- Restricted to the 60 globally-largest source/mediums so the payload stays small; the dashboard
-- sums the selected countries and re-ranks the top 15 for the Country-filtered sources table.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_sources_market` AS
WITH top AS (
  SELECT session_source_medium
  FROM `bidbrain-analytics.client_stt.stg_ga4`
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
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
  AND session_source_medium IN (SELECT session_source_medium FROM top)
GROUP BY market, source_medium;
