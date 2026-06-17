-- paid_creatives_model: per-channel/market/creative delivery over the whole window
-- (no date) -- powers the "Top & bottom performing creatives" tables. BigQuery port
-- of the creative-grain union that used to live as PAID_CREATIVES_SQL in job/main.py
-- (run against the Snowflake V_STG_* views). Same channel filters + market derivation
-- as paid_media_model, but grouped by creative instead of date. The dashboard filters
-- these by market chip only (rows carry no date) and ranks client-side.
CREATE OR REPLACE VIEW `client_cloudflare.paid_creatives_model` AS
WITH linkedin AS (
    SELECT
        'LinkedIn' AS CHANNEL,
        CASE
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-in%'    THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-tcn%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%_jp_%' OR LOWER(CAMPAIGN_NAME) LIKE '%apac-jp%' THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%_kr_%' OR LOWER(CAMPAIGN_NAME) LIKE '%apac-kr%' THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%rig%'        THEN 'RIG'
            ELSE 'UNMAPPED'
        END AS MARKET,
        COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), NULLIF(TRIM(AD_TITLE), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, SUM(LEADS) AS LEADS
    FROM `client_cloudflare.stg_linkedin`
    WHERE STARTS_WITH(CAMPAIGN_NAME, 'CLOUD_ACQ_')
    GROUP BY 2, 3
),
tradedesk AS (
    SELECT
        'TTD' AS CHANNEL,
        MARKET_L3 AS MARKET,
        COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS
    FROM `client_cloudflare.stg_tradedesk`
    WHERE MARKET_L3 IS NOT NULL AND MARKET_L3 <> ''
    GROUP BY 2, 3
),
reddit AS (
    SELECT
        'Reddit' AS CHANNEL,
        CASE
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%saarc%' OR LOWER(CAMPAIGN_NAME) LIKE '%india%' THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%gcr%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%jp%'    THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%kr%'    THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%rig%'   THEN 'RIG'
            ELSE 'ANZ'
        END AS MARKET,
        COALESCE(NULLIF(TRIM(AD_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS
    FROM `client_cloudflare.stg_reddit`
    GROUP BY 2, 3
),
line_jp AS (
    SELECT
        'LINE' AS CHANNEL,
        'JP' AS MARKET,
        COALESCE(NULLIF(TRIM(AD_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS,
        ROUND(SUM(COST) / 155.0, 2) AS SPEND_USD, 0 AS LEADS
    FROM `client_cloudflare.stg_line`
    GROUP BY 3
)
SELECT CHANNEL, MARKET, CREATIVE, IMPS, CLICKS, SPEND_USD, LEADS
FROM (
    SELECT * FROM linkedin
    UNION ALL SELECT * FROM tradedesk
    UNION ALL SELECT * FROM reddit
    UNION ALL SELECT * FROM line_jp
)
WHERE IMPS > 0;
