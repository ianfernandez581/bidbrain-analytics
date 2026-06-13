-- PropTrack (Transmission) — LinkedIn delivery by campaign (whole flight), for the detail table.
-- 16 campaigns; the dashboard shows the raw name with a light de-underscore fallback. Spend AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.li_campaigns` AS
SELECT
  campaign_name,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(engagements) AS engagements,
  SUM(video_views) AS video_views,
  SUM(leads)       AS leads,
  MIN(metric_date) AS start_date,
  MAX(metric_date) AS end_date
FROM `bidbrain-analytics.client_proptrack.stg_linkedin`
GROUP BY campaign_name
ORDER BY spend_aud DESC;
