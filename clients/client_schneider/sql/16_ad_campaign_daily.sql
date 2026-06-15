-- Schneider Electric — ad delivery by campaign × DAY, for the Day option of the VIEW BY grain
-- toggle on the Campaign-filtered Portfolio (cumulative spend) + Funnel (monthly delivery)
-- charts. Day key = FORMAT_DATE %Y-%m-%d. Delivering rows only (outer WHERE, not HAVING —
-- see 08). Mirrors ad_campaign_weekly (10) / ad_campaign_monthly (09), just the day grain.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    FORMAT_DATE('%Y-%m-%d', metric_date) AS day,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY day, platform, campaign;
