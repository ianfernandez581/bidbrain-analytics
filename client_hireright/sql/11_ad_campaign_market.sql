-- HireRight - ad delivery by campaign x market, for the Market filter + the
-- by-market charts (Overview spend-by-market bar across all platforms, and the Paid
-- Media spend & impressions by country for DV360). market is DV360's real country
-- for DV360 rows and 'Global' for TradeDesk + LinkedIn air-cover. The dashboard sums
-- the selected campaigns (and markets) per platform/market. Delivering rows only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaign_market` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    market,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_usd) AS spend_usd
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  WHERE market IS NOT NULL
  GROUP BY platform, campaign, market
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY platform, campaign, imps DESC;
