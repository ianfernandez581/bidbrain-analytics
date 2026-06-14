-- TLM — ad delivery by campaign (whole flight): the Campaign filter's option list +
-- per-campaign totals. One row per platform × campaign, delivering campaigns only.
-- Ordered by spend so the dropdown surfaces the campaigns that matter first. The dashboard
-- sums the selected campaigns client-side to rescale every ad-delivery figure. Revenue
-- and conversions come from Google only (TTD has NULL). Outer WHERE (not HAVING) so the
-- SUM aliases aren't re-aggregated.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,
    SUM(revenue)     AS revenue,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_tlm.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;