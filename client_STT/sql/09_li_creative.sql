-- STT GDC — LinkedIn delivery by creative type (whole flight).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.li_creative` AS
SELECT
  creative_type,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(cost_usd)    AS cost_usd,
  SUM(video_views) AS video_views,
  SUM(engagements) AS engagements
FROM `bidbrain-analytics.client_stt.stg_linkedin`
GROUP BY creative_type
ORDER BY imps DESC;
