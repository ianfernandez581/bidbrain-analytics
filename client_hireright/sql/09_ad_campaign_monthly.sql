-- HireRight - ad delivery by campaign x month, for the Campaign-filtered monthly
-- charts (Overview hero spend + Paid Media monthly delivery). The dashboard sums the
-- selected campaigns per month/platform. Month key mirrors `monthly` (FORMAT_DATE
-- %Y-%m). Delivering rows only (outer WHERE, not HAVING - see 08).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaign_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_usd) AS spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform, campaign, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY month, platform, campaign;
