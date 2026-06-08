-- ResetData — ad delivery by campaign × ISO week (campaign window), for the Campaign-filtered
-- Ads → Traffic weekly chart + correlation scatter. Week is Monday-anchored to match `weekly`.
-- From 2025-12-01 so the week list lines up with the GA4 weekly series. Delivering rows only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ad_campaign_weekly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_resetdata.stg_ad_delivery`
  WHERE metric_date >= DATE '2025-12-01'
  GROUP BY platform, campaign, week_start
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY week_start, platform, campaign;
