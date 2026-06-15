-- STT GDC — ad delivery by campaign × DAY (campaign window). Day-grain mirror of
-- ad_campaign_monthly (20) + ad_campaign_weekly (21): the Campaign filter sums the
-- selected campaigns per day/platform when "VIEW BY → Day" is set on the hero /
-- paid-monthly / link-weekly charts. From 2025-06-01 (the campaign window) so the
-- day list lines up with the GA4 daily series. Delivering rows only (outer WHERE).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    metric_date AS day,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_sgd) AS spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_ad_delivery`
  WHERE metric_date >= DATE '2025-06-01'
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_sgd > 0
ORDER BY day, platform, campaign;
