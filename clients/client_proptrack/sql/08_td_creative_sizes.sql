-- PropTrack (Transmission) — The Trade Desk delivery by creative size (AD_TYPE, whole flight).
-- e.g. 728x90, 320x100, 300x250, 160x600, 300x600 (Display) and 480x360 (Video). By impressions.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.td_creative_sizes` AS
SELECT
  creative_size,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud
FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
GROUP BY creative_size
ORDER BY imps DESC;
