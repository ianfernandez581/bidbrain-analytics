-- City Perfume — ad delivery by campaign x month. Lets the Overview/Paid-Media monthly ad
-- spend recompute when a subset of campaigns is selected (the all-campaigns sum reproduces
-- monthly.ad_spend exactly — the STT invariant). All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ad_campaign_monthly` AS
SELECT
  platform,
  campaign,
  DATE_TRUNC(metric_date, MONTH)  AS month,
  SUM(imps)                       AS imps,
  SUM(clicks)                     AS clicks,
  SUM(spend_aud)                  AS spend_aud,
  SUM(platform_conversions)       AS platform_conversions,
  SUM(platform_revenue)           AS platform_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
GROUP BY platform, campaign, month
ORDER BY month, spend_aud DESC;
