-- VMCH — ad delivery by campaign × month.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ad_campaign_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`
  GROUP BY platform, campaign, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY month, platform, campaign;