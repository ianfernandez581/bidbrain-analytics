CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_tradedesk` AS
SELECT DAY, CAMPAIGN_NAME, AD_GROUP_NAME, CREATIVE_FORMAT, PUBLISHER,
  IMPRESSIONS, COSTS, CLICKS, CONVERSIONS,
  SPLIT(CAMPAIGN_NAME, "_")[SAFE_OFFSET(2)] AS PROGRAMME,
  SPLIT(CAMPAIGN_NAME, "_")[SAFE_OFFSET(5)] AS MARKET,
  SPLIT(AD_GROUP_NAME, "_")[SAFE_OFFSET(6)] AS STRATEGY,
  SPLIT(CAMPAIGN_NAME, "_")[SAFE_OFFSET(4)] AS OBJECTIVE
FROM (
  -- Was client_mongodb.src_tradedesk (landed by the export job's TD_SQL).
  -- Now reads the shared raw mirror (snowflake_data_pull) and reproduces the
  -- old TD_SQL projection + advertiser filter here. IMPRESSIONS/CLICKS cast back
  -- to INT64 to match the old src_tradedesk schema.
  SELECT DAY, CAMPAIGN_NAME, AD_GROUP_NAME,
         AD_TYPE AS CREATIVE_FORMAT, PARTNER_NAME AS PUBLISHER,
         CAST(COALESCE(IMPRESSIONS, IMPRESSION) AS INT64) AS IMPRESSIONS,
         COSTS, CAST(CLICKS AS INT64) AS CLICKS,
         TOTAL_CLICK_PLUS_VIEW_CONVERSIONS AS CONVERSIONS
  FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
  WHERE ADVERTISER_NAME = "MongoDB"
)
