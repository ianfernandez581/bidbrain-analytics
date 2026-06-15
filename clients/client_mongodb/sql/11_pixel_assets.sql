-- Content engagement: Universal Pixel landing-page views per CONTENT asset.
-- Reads the melted seed (seed_pixel.py); 'default' (the catch-all site pixel,
-- dominated by inflated view-through site visits) is excluded here and reported
-- separately in pixel_summary so the chart shows only the named content pages.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.pixel_assets` AS
SELECT
  ASSET_KEY,
  ANY_VALUE(ASSET)  AS ASSET,
  SUM(TOTAL_CONV)   AS TOTAL_CONV,
  SUM(CLICK_CONV)   AS CLICK_CONV,
  SUM(VIEW_CONV)    AS VIEW_CONV
FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel_assets`
WHERE ASSET_KEY != 'default'
GROUP BY ASSET_KEY
ORDER BY TOTAL_CONV DESC
