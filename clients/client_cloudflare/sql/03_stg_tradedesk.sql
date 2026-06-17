-- stg_tradedesk: Cloudflare's Trade Desk slice + the campaign-name parsing.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_TRADEDESK_CF, now reading
-- raw_snowflake.tradedesk_apac_all instead of APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL".
-- Snowflake -> BigQuery ports:
--   SPLIT_PART(name,'_',N)  -> SPLIT(name,'_')[SAFE_OFFSET(N-1)] (wrapped IFNULL '' to
--                              mirror Snowflake's empty-string-on-overflow, since the
--                              final model filters MARKET_L3 <> '' / IS NOT NULL).
--   ILIKE '%x%'             -> LOWER(col) LIKE '%x%'
--   COALESCE(IMPRESSIONS, IMPRESSION) keeps the singular-column fallback (see CLAUDE.md).
CREATE OR REPLACE VIEW `client_cloudflare.stg_tradedesk` AS
SELECT
    DAY,
    ADVERTISER_NAME,
    CAMPAIGN_NAME,
    AD_GROUP_NAME,
    CREATIVE_NAME,
    AD_TYPE      AS CREATIVE_FORMAT,
    PARTNER_NAME AS PUBLISHER,
    COALESCE(IMPRESSIONS, IMPRESSION)   AS IMPRESSIONS,
    COSTS,
    CLICKS,
    TOTAL_CLICK_PLUS_VIEW_CONVERSIONS   AS CONVERSIONS,
    IFNULL(SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(8)],  '') AS MARKET_L3,
    IFNULL(SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(9)],  '') AS FUNNEL_STAGE,
    IFNULL(SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(12)], '') AS RAW_OBJECTIVE,
    CASE
        WHEN SPLIT(CAMPAIGN_NAME, '_')[SAFE_OFFSET(12)] = 'AWARENESS' THEN 'Awareness'
        ELSE 'Consideration'
    END AS FUNNEL_OBJECTIVE,
    CASE
        WHEN LOWER(CAMPAIGN_NAME) LIKE '%retargeting%'
          OR LOWER(CAMPAIGN_NAME) LIKE '%rtg%'
            THEN 'Retargeting'
        ELSE 'Prospecting'
    END AS CAMPAIGN_TYPE
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'Cloudflare';
