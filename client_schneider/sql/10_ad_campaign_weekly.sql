-- Schneider Electric — ad delivery by campaign × ISO week (Monday-anchored), for the
-- Campaign-filtered weekly spend / pacing + flight-overlap timeline. Delivering rows only
-- (outer WHERE). Mirrors client_STT/sql/21.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaign_weekly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
  GROUP BY platform, campaign, week_start
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY week_start, platform, campaign;
