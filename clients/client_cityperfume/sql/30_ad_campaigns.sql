-- City Perfume — ad delivery by campaign (whole window): the Campaign filter's option list
-- + per-campaign totals. One row per platform x campaign, delivering campaigns only
-- (zero-impression/zero-spend shells dropped). Ordered by spend so the searchable
-- multi-select surfaces what matters first. The dashboard sums the selected campaigns
-- client-side to rescale every ad-delivery figure (sales side stays whole). Mirrors STT.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)                  AS imps,
    SUM(clicks)                AS clicks,
    SUM(spend_aud)             AS spend_aud,
    SUM(platform_conversions)  AS platform_conversions,
    SUM(platform_revenue)      AS platform_revenue,
    MIN(metric_date)           AS start_date,
    MAX(metric_date)           AS end_date
  FROM `bidbrain-analytics.client_cityperfume.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
