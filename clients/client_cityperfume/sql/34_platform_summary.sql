-- City Perfume — per-platform delivery summary (Paid Media comparison table). Includes
-- each platform's PLATFORM-CLAIMED ROAS (its own conversions_value/purchase_value over its
-- own spend) shown SEPARATELY and clearly labelled — this is NOT the blended ROAS and is
-- never summed across platforms. TTD has no revenue in-source so its claimed ROAS is NULL
-- (it stays an upper-funnel/awareness channel; platform_conversions = view-through count).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.platform_summary` AS
SELECT
  platform,
  SUM(spend_aud)                                    AS spend_aud,
  SUM(imps)                                         AS imps,
  SUM(clicks)                                       AS clicks,
  SAFE_DIVIDE(SUM(clicks), SUM(imps))               AS ctr,
  SAFE_DIVIDE(SUM(spend_aud), SUM(clicks))          AS cpc,
  SUM(platform_conversions)                         AS platform_conversions,
  SUM(platform_revenue)                             AS platform_revenue_claimed,
  SAFE_DIVIDE(SUM(platform_revenue), SUM(spend_aud)) AS platform_claimed_roas,
  SAFE_DIVIDE(SUM(spend_aud), SUM(platform_conversions)) AS cost_per_conversion
FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
GROUP BY platform
ORDER BY spend_aud DESC;
