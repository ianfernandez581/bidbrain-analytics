-- STT GDC — top website source / medium (campaign window).
-- The granular view of where sessions originate — this is where the ad platforms
-- surface by name: "googledv360 / banner" (DV360 programmatic) and
-- "linkedin / paid-social" (LinkedIn) sit right next to organic/direct/referral,
-- making the ad contribution legible. Capped at the top 40 by sessions.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ga4_sources` AS
SELECT
  session_source_medium      AS source_medium,
  ANY_VALUE(channel_group)   AS channel_group,
  ANY_VALUE(channel_bucket)  AS channel_bucket,
  SUM(sessions)              AS sessions,
  SUM(engaged_sessions)      AS engaged_sessions,
  SUM(conversions)           AS conversions
FROM `bidbrain-analytics.client_stt.stg_ga4`
WHERE metric_date >= DATE '2025-06-01'
GROUP BY source_medium
ORDER BY sessions DESC
LIMIT 40;
