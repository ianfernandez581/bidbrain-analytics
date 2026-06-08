-- ResetData — top GA4 source/medium by sessions (global top-N), ad platforms flagged.
--
-- The Website tab's "top sources" table. is_ad flags the rows that come from the three paid
-- platforms (google / cpc, meta + ig + facebook, tradedesk + ttd + adsrvr) so stakeholders can
-- see paid vs organic/direct sources at a glance. Top 25 by sessions.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga4_sources` AS
SELECT
  source_medium,
  ANY_VALUE(channel_group)  AS channel_group,
  ANY_VALUE(channel_bucket) AS channel_bucket,
  SUM(sessions)             AS sessions,
  SUM(engaged_sessions)     AS engaged_sessions,
  SUM(conversions)          AS conversions,
  LOGICAL_OR(
    REGEXP_CONTAINS(LOWER(source_medium), r'google\s*/\s*cpc|/\s*paid|tradedesk|adsrvr|ttd|meta|facebook|instagram|(^|[^a-z])ig\b')
  ) AS is_ad
FROM `bidbrain-analytics.client_resetdata.stg_ga4`
GROUP BY source_medium
ORDER BY sessions DESC
LIMIT 25;
