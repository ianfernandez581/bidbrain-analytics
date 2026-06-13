-- PropTrack (Transmission) — ad delivery by campaign × day, for the Campaign-filtered TradeDesk
-- daily chart (Programmatic tab). The dashboard sums the selected campaigns per day/platform.
-- Delivering rows only (outer WHERE). (LinkedIn rows exist too, but the daily chart reads the
-- tradedesk platform only — kept here so the contract stays platform-agnostic.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.ad_campaign_daily` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    metric_date AS day,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions
  FROM `bidbrain-analytics.client_proptrack.stg_ad_delivery`
  GROUP BY platform, campaign, day
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY day, platform, campaign;
