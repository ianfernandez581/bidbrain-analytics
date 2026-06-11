-- City Perfume — ad delivery by campaign x DAY (range-aware spine of every ad-side figure:
-- Overview/Paid KPIs, spend donuts, platform-compare table, top-campaigns table, and the
-- spend/ROAS trend charts). Day grain so the dashboard clips to the exact range, applies the
-- Campaign/Platform filters client-side, and aggregates up. The all-campaigns sum reproduces
-- the whole-period ad_campaigns totals exactly. platform_revenue is each platform's own-CLAIMED
-- revenue (context, never the blended headline). All AUD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ad_campaign_daily` AS
SELECT
  platform,
  campaign,
  metric_date               AS day,
  SUM(imps)                 AS imps,
  SUM(clicks)               AS clicks,
  SUM(spend_aud)            AS spend_aud,
  SUM(platform_conversions) AS platform_conversions,
  SUM(platform_revenue)     AS platform_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
GROUP BY platform, campaign, day
ORDER BY day, spend_aud DESC;
