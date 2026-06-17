-- Content engagement (Trade Desk Universal Pixel) — LIVE staging, replacing the
-- retired manual CSV seed (seed_pixel.py). One row per pixel FIRE in the shared
-- conversion mirror, rolled up here to CAMPAIGN_KEY × ASSET_KEY (the old
-- seed_tradedesk_pixel_assets shape, PLUS a CAMPAIGN_KEY dimension). The pixel_*
-- consumer views read THIS, not raw_snowflake.
--
-- Filter: ADVERTISER_ID = '9c1w83i' is MongoDB. The conversion table has no
-- ADVERTISER_NAME column, and this id is identical to filtering the MDB_UPM_* /
-- 'MongoDB Universal Pixel - Default' tracking tags (same 146,041 fires).
--
-- click vs view-through is DERIVED, not a labelled field: a fire with
-- DISPLAY_CLICK_COUNT > 0 is a click conversion, else view-through. (Validated:
-- the named content pixels are almost entirely clicked; the catch-all Default
-- site pixel is almost entirely view-through.)
--
-- CAMPAIGN_KEY (DNB vs KGA(IDC)) is derived per fire from the attributed campaign
-- name, the SAME convention as 01_stg_tradedesk (programme = 3rd '_'-field) and the
-- dashboard's campaignOf(): IDE/DNB -> 'DNB', else -> 'IDC'. Attribution source:
-- the click campaign first (the content pixels are click-driven), then the
-- impression campaign (the view-through site pixel) — the COALESCE recovers the
-- ~82% of content fires that are click conversions with a NULL impression campaign,
-- giving 100% attribution (zero fires where both names are NULL).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_tradedesk_pixel` AS
WITH fires AS (
  SELECT
    CASE
      WHEN REGEXP_CONTAINS(UPPER(
             SPLIT(COALESCE(FIRST_DISPLAY_CLICK_CAMPAIGN_NAME,
                            FIRST_IMPRESSION_CAMPAIGN_NAME), "_")[SAFE_OFFSET(2)]
           ), r'IDE|DNB') THEN 'DNB'
      ELSE 'IDC'                 -- KGA (IDC); no fire is left unattributed by the COALESCE above
    END AS CAMPAIGN_KEY,
    CASE TRACKING_TAG_NAME
      WHEN 'MDB_UPM_LPView_Gartner_MQ_Leader'  THEN 'gartner_mq'
      WHEN 'MDB_UPM_LPView_AI_Readiness'       THEN 'ai_readiness'
      WHEN 'MDB_UPM_LPView_AI_DataSilos'       THEN 'ai_datasilos'
      WHEN 'MDB_UPM_LPView_IDC_WinningAI'      THEN 'idc_winningai'
      WHEN 'MDB_UPM_LPView_Payments_Modernize' THEN 'payments_modernize'
      WHEN 'MDB_UPM_LPView_Payments_Instant'   THEN 'payments_instant'
      WHEN 'MongoDB Universal Pixel - Default' THEN 'default'
    END AS ASSET_KEY,
    DISPLAY_CLICK_COUNT,
    DAY
  FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_conversion`
  WHERE ADVERTISER_ID = '9c1w83i'
)
SELECT
  CAMPAIGN_KEY,
  ASSET_KEY,
  -- Human label, reproducing the retired seed's exact ASSET strings.
  CASE ASSET_KEY
    WHEN 'gartner_mq'         THEN 'Gartner MQ Leader'
    WHEN 'ai_readiness'       THEN 'AI Readiness'
    WHEN 'ai_datasilos'       THEN 'AI Data Silos'
    WHEN 'idc_winningai'      THEN 'IDC Winning AI'
    WHEN 'payments_modernize' THEN 'Payments Modernize'
    WHEN 'payments_instant'   THEN 'Payments Instant'
    WHEN 'default'            THEN 'All pages (Default)'
  END AS ASSET,
  COUNT(*)                                      AS TOTAL_CONV,
  COUNTIF(DISPLAY_CLICK_COUNT > 0)              AS CLICK_CONV,
  COUNTIF(COALESCE(DISPLAY_CLICK_COUNT, 0) = 0) AS VIEW_CONV,
  -- Window helpers, consumed per-campaign by pixel_summary.
  MIN(DAY)                                      AS START_DAY,
  MAX(DAY)                                      AS END_DAY
FROM fires
GROUP BY CAMPAIGN_KEY, ASSET_KEY
