-- PropTrack (Transmission) — ad delivery by campaign × month, for the Campaign-filtered Overview
-- hero (stacked spend by platform + impressions). The dashboard sums the selected campaigns per
-- month/platform. Month key matches `monthly` (FORMAT_DATE %Y-%m). Delivering rows only (outer WHERE).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.ad_campaign_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions
  FROM `bidbrain-analytics.client_proptrack.stg_ad_delivery`
  GROUP BY platform, campaign, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY month, platform, campaign;
