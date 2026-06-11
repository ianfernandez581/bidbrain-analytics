-- PropTrack (Transmission) — The Trade Desk delivery by ABM audience segment (whole flight).
-- segment = AD_GROUP_NAME with the campaign prefix stripped (see stg_tradedesk). 5 segments;
-- PARTNER-BROKER-DISTRIBUTION dominates (~80% of spend). Ordered by spend desc.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.td_segments` AS
SELECT
  segment,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(conversions) AS conv
FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
GROUP BY segment
ORDER BY spend_aud DESC;
