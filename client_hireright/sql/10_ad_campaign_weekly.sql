-- HireRight - ad delivery by campaign x ISO week (Monday-anchored, whole span), for
-- completeness + the CSV export. The dashboard sums the selected campaigns per week.
-- Delivering rows only (outer WHERE, not HAVING - see 08).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaign_weekly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_usd) AS spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform, campaign, week_start
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY week_start, platform, campaign;
