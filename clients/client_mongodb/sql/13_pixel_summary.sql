-- Content engagement: per-campaign headline for the pixel snapshot — the window it
-- covers, total delivery, and the conversion split. ONE ROW PER CAMPAIGN_KEY
-- ('DNB' / 'IDC') so the dashboard's campaign toggle can pick its slice.
--   CONTENT_* = the named content pixels (the real engagement signal);
--   DEFAULT_*  = the catch-all site pixel, kept separate and labelled as
--                "ad-influenced site visits" in the UI because it's dominated by
--                loose view-through attribution, not hard leads.
-- The conversion splits + window come from stg_tradedesk_pixel (the live pixel
-- feed); IMPS / COST_USD / CLICKS come from the already-live MongoDB Trade Desk
-- delivery (paid_media_model), mapped to the same campaign — so they stay
-- independent of the dashboard's region / date filters but follow the campaign.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.pixel_summary` AS
WITH px AS (
  SELECT
    CAMPAIGN_KEY,
    SUM(IF(ASSET_KEY =  'default', TOTAL_CONV, 0)) AS DEFAULT_TOTAL,
    SUM(IF(ASSET_KEY =  'default', VIEW_CONV,  0)) AS DEFAULT_VIEW,
    SUM(IF(ASSET_KEY =  'default', CLICK_CONV, 0)) AS DEFAULT_CLICK,
    SUM(IF(ASSET_KEY != 'default', TOTAL_CONV, 0)) AS CONTENT_TOTAL,
    SUM(IF(ASSET_KEY != 'default', CLICK_CONV, 0)) AS CONTENT_CLICK,
    SUM(IF(ASSET_KEY != 'default', VIEW_CONV,  0)) AS CONTENT_VIEW,
    SUM(TOTAL_CONV)                                AS ALL_CONV,
    MIN(START_DAY)                                 AS START_DAY,
    MAX(END_DAY)                                   AS END_DAY
  FROM `bidbrain-analytics.client_mongodb.stg_tradedesk_pixel`
  GROUP BY CAMPAIGN_KEY
),
deliv AS (
  -- MongoDB Trade Desk delivery for the same campaign. PROGRAMME -> DNB/IDC mirrors
  -- the dashboard's campaignOf(): IDE/DNB -> 'DNB', else -> 'IDC'.
  SELECT
    CASE WHEN REGEXP_CONTAINS(UPPER(PROGRAMME), r'IDE|DNB') THEN 'DNB' ELSE 'IDC' END AS CAMPAIGN_KEY,
    SUM(IMPS)      AS IMPS,
    SUM(SPEND_USD) AS COST_USD,
    SUM(CLICKS)    AS CLICKS
  FROM `bidbrain-analytics.client_mongodb.paid_media_model`
  GROUP BY 1
)
SELECT
  px.CAMPAIGN_KEY,
  px.START_DAY,
  px.END_DAY,
  DATE_DIFF(px.END_DAY, px.START_DAY, DAY) + 1 AS DAYS,   -- calendar span of the conversion window
  COALESCE(deliv.IMPS,     0) AS IMPS,
  COALESCE(deliv.COST_USD, 0) AS COST_USD,
  COALESCE(deliv.CLICKS,   0) AS CLICKS,
  px.ALL_CONV,
  px.DEFAULT_TOTAL,
  px.DEFAULT_VIEW,
  px.DEFAULT_CLICK,
  px.CONTENT_TOTAL,
  px.CONTENT_CLICK,
  px.CONTENT_VIEW
FROM px
LEFT JOIN deliv USING (CAMPAIGN_KEY)
ORDER BY px.CAMPAIGN_KEY
