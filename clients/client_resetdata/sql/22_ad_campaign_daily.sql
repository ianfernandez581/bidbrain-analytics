-- ResetData — ad delivery by campaign × DAY (the day-grain analogue of ad_campaign_weekly /
-- ad_campaign_monthly), for the Campaign-filtered "View by → Day" grain on the Overview hero,
-- Paid Media spend-by-platform, Reddit-over-time and Ads → Traffic trend charts. Day key
-- ('YYYY-MM-DD') matches `daily`. From 2025-12-01 so the day list lines up with the GA4 daily
-- series. Delivering rows only (outer WHERE), like ad_campaign_weekly / ad_campaign_monthly.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    metric_date AS day,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions
  FROM `bidbrain-analytics.client_resetdata.stg_ad_delivery`
  WHERE metric_date >= DATE '2025-12-01'
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY day, platform, campaign;
