-- VMCH — ad delivery by campaign × ISO week (campaign window).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.ad_campaign_weekly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud,
    SUM(post_view_conv)  AS post_view,
    SUM(post_click_conv) AS post_click
  FROM `bidbrain-analytics.client_vmch.stg_ad_delivery`
  WHERE metric_date >= DATE '2026-04-01'
  GROUP BY platform, campaign, week_start
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY week_start, platform, campaign;