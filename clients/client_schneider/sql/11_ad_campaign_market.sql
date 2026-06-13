-- Schneider Electric — ad delivery by campaign × market (whole flight), for the
-- Campaign-filtered Geography tab. All three platforms carry a market (DV360 from
-- COUNTRY_NAME; LinkedIn/TradeDesk parsed from the campaign name), so all three appear here.
-- market is FINE-grained (Australia / New Zealand / India / Singapore / … / coarse region for
-- the global spill); the dashboard rolls it up to the brief reporting region and can also show
-- the AU vs NZ split. Delivering rows only (outer WHERE). Mirrors client_STT/sql/22.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaign_market` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    market,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_aud) AS spend_aud
  FROM `bidbrain-analytics.client_schneider.stg_ad_delivery`
  WHERE market IS NOT NULL
  GROUP BY platform, campaign, market
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY platform, campaign, imps DESC;
