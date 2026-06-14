-- VMCH — ad delivery by campaign (whole flight), the Campaign filter's option list.
-- One row per platform × campaign, delivering campaigns only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;