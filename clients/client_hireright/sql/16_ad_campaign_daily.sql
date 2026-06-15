-- HireRight - ad delivery by campaign x day, for the Campaign-filtered Day view of
-- the monthly charts (Overview hero spend + Paid Media monthly delivery). Mirrors
-- ad_campaign_monthly (09) / ad_campaign_weekly (10) at the finest grain. The
-- dashboard sums the selected campaigns per day/platform. day key is an ISO
-- 'YYYY-MM-DD' string to match the dashboard's inRangeDay helper / adDailyMap.
-- Delivering rows only (outer WHERE, not HAVING - see 08).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_usd) AS spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY day, platform, campaign;
