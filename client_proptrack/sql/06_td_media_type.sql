-- PropTrack (Transmission) — The Trade Desk delivery by media type (Display vs Video, whole flight).
-- Video is pure awareness — it drove 0 conversions (all 924 conversions are Display).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.td_media_type` AS
SELECT
  media_type,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(conversions) AS conv
FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
GROUP BY media_type
ORDER BY spend_aud DESC;
