-- PropTrack (Transmission) — LinkedIn delivery by creative type (whole flight).
-- Two values: 'Sponsored Content (Standard)' and 'Video' (labelled in stg_linkedin). By impressions.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.li_creative` AS
SELECT
  creative_type,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(video_views) AS video_views,
  SUM(engagements) AS engagements
FROM `bidbrain-analytics.client_proptrack.stg_linkedin`
GROUP BY creative_type
ORDER BY imps DESC;
