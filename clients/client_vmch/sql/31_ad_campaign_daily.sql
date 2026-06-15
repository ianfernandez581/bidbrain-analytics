-- VMCH — ad delivery by campaign × day (campaign window). Mirrors 21_ad_campaign_weekly.sql
-- at metric_date grain so the spend/delivery trend charts can offer a Day view.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    metric_date AS day,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY day, platform, campaign;
