-- Schneider Electric — ad delivery by campaign × month, for the Campaign-filtered monthly
-- charts (spend trend + pacing). Month key matches `monthly` (FORMAT_DATE %Y-%m). Delivering
-- rows only (outer WHERE, not HAVING — see 08). Mirrors client_STT/sql/20.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaign_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
  GROUP BY platform, campaign, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY month, platform, campaign;
