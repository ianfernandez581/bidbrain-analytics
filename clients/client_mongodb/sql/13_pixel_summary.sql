-- Content engagement: one-row headline for the pixel snapshot — the window it
-- covers, total delivery, and the conversion split. CONTENT_* = the six named
-- content pixels (the real engagement signal); DEFAULT_* = the catch-all site
-- pixel, kept separate and labelled as "ad-influenced site visits" in the UI
-- because it's dominated by loose view-through attribution, not hard leads.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.pixel_summary` AS
WITH d AS (SELECT * FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel`),
     a AS (SELECT * FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel_assets`)
SELECT
  (SELECT MIN(DAY)            FROM d) AS START_DAY,
  (SELECT MAX(DAY)            FROM d) AS END_DAY,
  (SELECT COUNT(DISTINCT DAY) FROM d) AS DAYS,
  (SELECT SUM(IMPRESSIONS)    FROM d) AS IMPS,
  (SELECT SUM(COST_USD)       FROM d) AS COST_USD,
  (SELECT SUM(CLICKS)         FROM d) AS CLICKS,
  (SELECT SUM(ALL_CONV)       FROM d) AS ALL_CONV,
  (SELECT SUM(TOTAL_CONV) FROM a WHERE ASSET_KEY =  'default') AS DEFAULT_TOTAL,
  (SELECT SUM(VIEW_CONV)  FROM a WHERE ASSET_KEY =  'default') AS DEFAULT_VIEW,
  (SELECT SUM(CLICK_CONV) FROM a WHERE ASSET_KEY =  'default') AS DEFAULT_CLICK,
  (SELECT SUM(TOTAL_CONV) FROM a WHERE ASSET_KEY != 'default') AS CONTENT_TOTAL,
  (SELECT SUM(CLICK_CONV) FROM a WHERE ASSET_KEY != 'default') AS CONTENT_CLICK,
  (SELECT SUM(VIEW_CONV)  FROM a WHERE ASSET_KEY != 'default') AS CONTENT_VIEW
