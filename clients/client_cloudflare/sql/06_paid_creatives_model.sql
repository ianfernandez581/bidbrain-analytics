-- paid_creatives_model: per-channel/market/creative delivery over the whole window
-- (no date) -- powers the "Top & bottom performing creatives" tables. BigQuery port
-- of the creative-grain union that used to live as PAID_CREATIVES_SQL in job/main.py
-- (run against the Snowflake V_STG_* views). Same channel filters + market derivation
-- as paid_media_model, but grouped by creative instead of date. The dashboard filters
-- these by market chip only (rows carry no date) and ranks client-side.
--
-- 2026-08-14 - carries PROGRAM (CORE_DG / SURROUND_ABM) as column 2 of every arm, matching
-- paid_media_model, so the creative tables follow the lane selector. Without it the Surround
-- ABM lane would list Core DG's creatives (these rows have no date, so the quarter/date
-- filters can't separate them either).
CREATE OR REPLACE VIEW `client_cloudflare.paid_creatives_model` AS
WITH linkedin AS (
    SELECT
        'LinkedIn' AS CHANNEL,
        PROGRAM AS PROGRAM,
        -- CAMPAIGN_NAME_NORM = brief-number prefix stripped (stg_linkedin, 2026-08-04);
        -- keep these rules identical to paid_media_model's LinkedIn arm.
        CASE
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-in%'    THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-tcn%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%_jp_%' OR LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-jp%' THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%_kr_%' OR LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-kr%' THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%rig%'        THEN 'RIG'
            ELSE 'UNMAPPED'
        END AS MARKET,
        COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), NULLIF(TRIM(AD_TITLE), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, SUM(LEADS) AS LEADS
    FROM `client_cloudflare.stg_linkedin`
    WHERE STARTS_WITH(CAMPAIGN_NAME_NORM, 'CLOUD_ACQ_')
    GROUP BY 2, 3, 4
),
tradedesk AS (
    SELECT
        'TTD' AS CHANNEL,
        PROGRAM AS PROGRAM,
        MARKET_L3 AS MARKET,
        COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS
    FROM `client_cloudflare.stg_tradedesk`
    WHERE MARKET_L3 IS NOT NULL AND MARKET_L3 <> ''
    GROUP BY 2, 3, 4
),
reddit AS (
    SELECT
        'Reddit' AS CHANNEL,
        CASE
            WHEN LOWER(IFNULL(CAMPAIGN_NAME, '')) LIKE '%surround%abm%'
              OR STARTS_WITH(TRIM(IFNULL(CAMPAIGN_NAME, '')), '2193_')
                THEN 'SURROUND_ABM'
            ELSE 'CORE_DG'
        END AS PROGRAM,
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
    GROUP BY 2, 3, 4
),
line_jp AS (
    SELECT
        'LINE' AS CHANNEL,
        'CORE_DG' AS PROGRAM,
        'JP' AS MARKET,
        COALESCE(NULLIF(TRIM(AD_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS,
        ROUND(SUM(COST) / 155.0, 2) AS SPEND_USD, 0 AS LEADS
    FROM `client_cloudflare.stg_line`
    GROUP BY 4
)
SELECT CHANNEL, PROGRAM, MARKET, CREATIVE, IMPS, CLICKS, SPEND_USD, LEADS
FROM (
    SELECT * FROM linkedin
    UNION ALL SELECT * FROM tradedesk
    UNION ALL SELECT * FROM reddit
    UNION ALL SELECT * FROM line_jp
)
WHERE IMPS > 0;
