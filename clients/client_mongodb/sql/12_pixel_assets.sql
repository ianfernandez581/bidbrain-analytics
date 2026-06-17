-- Content engagement: Universal Pixel landing-page views per CONTENT asset, per
-- campaign. Reads the live staging view (stg_tradedesk_pixel); 'default' (the
-- catch-all site pixel, dominated by view-through site visits) is excluded here and
-- reported separately in pixel_summary so the chart shows only the named content
-- pages. CAMPAIGN_KEY ('DNB' | 'IDC') lets the dashboard's campaign toggle filter
-- this list client-side (under KGA(IDC) the list is legitimately sparse — only 122
-- content fires across the flight — not a bug).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.pixel_assets` AS
SELECT
  CAMPAIGN_KEY,
  ASSET_KEY,
  ANY_VALUE(ASSET)  AS ASSET,
  SUM(TOTAL_CONV)   AS TOTAL_CONV,
  SUM(CLICK_CONV)   AS CLICK_CONV,
  SUM(VIEW_CONV)    AS VIEW_CONV
FROM `bidbrain-analytics.client_mongodb.stg_tradedesk_pixel`
WHERE ASSET_KEY != 'default'
GROUP BY CAMPAIGN_KEY, ASSET_KEY
ORDER BY CAMPAIGN_KEY, TOTAL_CONV DESC
