-- Schneider Electric — ad delivery by campaign (whole flight): the Campaign filter's option
-- list + per-campaign totals. One row per platform × campaign, delivering campaigns only.
-- Ordered by spend so the dropdown surfaces what matters first. The dashboard sums the
-- selected campaigns client-side to rescale every ad-delivery figure, and joins each campaign
-- to its internal campaign via seed_campaign_map.match_pattern (CONTAINS).
--
-- "Delivering only" is an OUTER WHERE, NOT HAVING — BigQuery resolves HAVING against SELECT
-- aliases, which would re-aggregate the SUMs. (Mirrors client_STT/sql/19_ad_campaigns.sql.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
