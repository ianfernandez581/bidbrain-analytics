-- HireRight - ad delivery by campaign (whole flight): the Campaign filter's option
-- list + per-campaign totals. One row per platform x campaign, delivering campaigns
-- only (zero-impression / zero-spend shells dropped). Ordered by spend so the
-- dropdown surfaces the campaigns that matter at the top. The dashboard sums the
-- selected campaigns client-side to rescale every ad-delivery figure.
-- (Delivering filter is an outer WHERE, not HAVING, so the SUM aliases below don't
-- get re-aggregated - BigQuery resolves HAVING against SELECT aliases.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_usd)   AS spend_usd,
    SUM(conversions) AS conversions,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY spend_usd DESC;
