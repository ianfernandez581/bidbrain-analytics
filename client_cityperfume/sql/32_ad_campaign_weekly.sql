-- City Perfume — ad delivery by campaign x ISO week (Monday). Powers the Ads -> Revenue
-- weekly spend line under the Campaign filter (sales revenue stays whole-store weekly).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ad_campaign_weekly` AS
SELECT
  platform,
  campaign,
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  SUM(spend_aud)                        AS spend_aud,
  SUM(imps)                             AS imps,
  SUM(clicks)                           AS clicks,
  SUM(platform_conversions)             AS platform_conversions
FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
GROUP BY platform, campaign, week_start
ORDER BY week_start, spend_aud DESC;
