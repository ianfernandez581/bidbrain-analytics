-- MongoDB - LinkedIn delivery by campaign (whole flight), for the LinkedIn tab's detail table.
-- One row per campaign; additive base only (CTR/CPC/CPM/CPL derived in the dashboard). Empty
-- until the Windsor account is readable.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.linkedin_by_campaign` AS
SELECT
  campaign_name,
  campaign_group_name,
  objective_type,
  ANY_VALUE(currency)      AS currency,
  SUM(imps)                AS imps,
  SUM(clicks)              AS clicks,
  SUM(spend_usd)           AS spend_usd,
  SUM(spend_native)        AS spend_native,
  SUM(leads)               AS leads,
  SUM(lead_form_opens)     AS lead_form_opens,
  SUM(video_views)         AS video_views,
  SUM(engagements)         AS engagements,
  MIN(metric_date)         AS start_date,
  MAX(metric_date)         AS end_date
FROM `bidbrain-analytics.client_mongodb.stg_linkedin`
GROUP BY campaign_name, campaign_group_name, objective_type
ORDER BY imps DESC;
