-- STT GDC — ad delivery by campaign × month, for the Campaign-filtered monthly
-- charts (Overview hero impressions + Paid Media spend-by-platform). The dashboard
-- sums the selected campaigns per month/platform. Mirrors the month key in `monthly`
-- (FORMAT_DATE %Y-%m). Delivering rows only (outer WHERE, not HAVING — see 19).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ad_campaign_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_sgd) AS spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_ad_delivery`
  GROUP BY platform, campaign, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_sgd > 0
ORDER BY month, platform, campaign;
