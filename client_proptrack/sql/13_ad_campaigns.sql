-- PropTrack (Transmission) — ad delivery by campaign (whole flight): the Campaign filter's option
-- list + per-campaign totals. One row per platform × campaign, delivering campaigns only (zero
-- shells dropped via an outer WHERE, not HAVING, so the SUM aliases aren't re-aggregated). Ordered
-- by spend desc so the dropdown surfaces the campaigns that matter at the top. The dashboard sums
-- the selected campaigns client-side to rescale every combined ad-delivery figure.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_proptrack.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
