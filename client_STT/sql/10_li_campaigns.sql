-- STT GDC — LinkedIn delivery by campaign (whole flight), for the detail table.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.li_campaigns` AS
SELECT
  campaign_name,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(cost_usd)    AS cost_usd,
  SUM(video_views) AS video_views,
  MIN(metric_date) AS start_date,
  MAX(metric_date) AS end_date
FROM `bidbrain-analytics.client_stt.stg_linkedin`
GROUP BY campaign_name
ORDER BY imps DESC;
