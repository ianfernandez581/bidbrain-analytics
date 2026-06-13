-- HireRight - LinkedIn delivery by campaign (whole flight), for the detail table.
-- cost_usd is USD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.li_campaigns` AS
SELECT
  campaign_name,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(cost_usd)    AS cost_usd,
  SUM(video_views) AS video_views,
  SUM(leads)       AS leads,
  MIN(metric_date) AS start_date,
  MAX(metric_date) AS end_date
FROM `bidbrain-analytics.client_hireright.stg_linkedin`
GROUP BY campaign_name
ORDER BY imps DESC;
