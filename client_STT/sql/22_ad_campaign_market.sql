-- STT GDC — ad delivery by campaign × market (whole flight), for the
-- Campaign-filtered Paid Media by-market charts (Google Ads + DV360). LinkedIn has
-- no market grain (market IS NULL) so it is excluded here — it isn't charted by
-- market anyway. The dashboard sums the selected campaigns per market/platform.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ad_campaign_market` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    market,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_sgd) AS spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_ad_delivery`
  WHERE market IS NOT NULL
  GROUP BY platform, campaign, market
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_sgd > 0
ORDER BY platform, campaign, imps DESC;
