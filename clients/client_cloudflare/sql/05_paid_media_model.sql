-- paid_media_model: per-channel/market/day paid delivery for the dashboard.
-- BigQuery port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL:
-- a UNION ALL of the four staging views with market derivation, weekly rollup key,
-- and JPY->USD@155 for LINE. Replaces the old thin pass-through of src_paid_media.
-- Snowflake -> BigQuery ports:
--   DATE_TRUNC('WEEK', d)::DATE  -> DATE_TRUNC(d, WEEK(MONDAY))  (Snowflake weeks start Monday)
--   ILIKE '%x%'                  -> LOWER(col) LIKE '%x%'
--   LIKE 'CLOUD\_ACQ\_%' ESCAPE  -> STARTS_WITH(CAMPAIGN_NAME,'CLOUD_ACQ_')
-- Column/label contract (CHANNEL, MARKET strings) is unchanged from the dashboard's
-- expectations (TTD/LinkedIn/Reddit/LINE; the 7 L1 markets + raw TTD MARKET_L3).
CREATE OR REPLACE VIEW `client_cloudflare.paid_media_model` AS
WITH linkedin AS (
    SELECT
        'LinkedIn'                       AS CHANNEL,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        CASE
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-in%'    THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%apac-tcn%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%_jp_%' OR LOWER(CAMPAIGN_NAME) LIKE '%apac-jp%' THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%_kr_%' OR LOWER(CAMPAIGN_NAME) LIKE '%apac-kr%' THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%rig%'        THEN 'RIG'
            ELSE 'UNMAPPED'
        END                              AS MARKET,
        SUM(IMPRESSIONS)                 AS IMPS,
        SUM(CLICKS)                      AS CLICKS,
        SUM(COSTS)                       AS SPEND_USD,
        SUM(LEADS)                       AS LEADS,
        SUM(LEAD_FORM_OPENS)             AS FORM_OPENS,
        SUM(LINK_CLICKS)                 AS LINK_CLICKS,
        SUM(ACTION_CLICKS)               AS ACTION_CLICKS,
        SUM(VIDEO_STARTS)                AS VIDEO_STARTS,
        SUM(VIDEO_COMPLETIONS)           AS VIDEO_COMPLETIONS,
        CAST(NULL AS FLOAT64)            AS SPEND_JPY,
        CAST(NULL AS FLOAT64)            AS FX_USD_JPY
    FROM `client_cloudflare.stg_linkedin`
    WHERE STARTS_WITH(CAMPAIGN_NAME, 'CLOUD_ACQ_')
    GROUP BY 2, 3, 4
),
tradedesk AS (
    SELECT
        'TTD'                            AS CHANNEL,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        MARKET_L3                        AS MARKET,
        SUM(IMPRESSIONS)                 AS IMPS,
        SUM(CLICKS)                      AS CLICKS,
        SUM(COSTS)                       AS SPEND_USD,
        0                                AS LEADS,
        CAST(NULL AS FLOAT64)            AS FORM_OPENS,
        CAST(NULL AS FLOAT64)            AS LINK_CLICKS,
        CAST(NULL AS FLOAT64)            AS ACTION_CLICKS,
        CAST(NULL AS FLOAT64)            AS VIDEO_STARTS,
        CAST(NULL AS FLOAT64)            AS VIDEO_COMPLETIONS,
        CAST(NULL AS FLOAT64)            AS SPEND_JPY,
        CAST(NULL AS FLOAT64)            AS FX_USD_JPY
    FROM `client_cloudflare.stg_tradedesk`
    WHERE MARKET_L3 IS NOT NULL AND MARKET_L3 <> ''
    GROUP BY 2, 3, 4
),
reddit AS (
    SELECT
        'Reddit'                         AS CHANNEL,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        CASE
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%saarc%' OR LOWER(CAMPAIGN_NAME) LIKE '%india%' THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%gcr%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%jp%'    THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%kr%'    THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME) LIKE '%rig%'   THEN 'RIG'
            ELSE 'ANZ'
        END                              AS MARKET,
        SUM(IMPRESSIONS)                 AS IMPS,
        SUM(CLICKS)                      AS CLICKS,
        SUM(COSTS)                       AS SPEND_USD,
        0                                AS LEADS,
        CAST(NULL AS FLOAT64)            AS FORM_OPENS,
        CAST(NULL AS FLOAT64)            AS LINK_CLICKS,
        CAST(NULL AS FLOAT64)            AS ACTION_CLICKS,
        CAST(NULL AS FLOAT64)            AS VIDEO_STARTS,
        CAST(NULL AS FLOAT64)            AS VIDEO_COMPLETIONS,
        CAST(NULL AS FLOAT64)            AS SPEND_JPY,
        CAST(NULL AS FLOAT64)            AS FX_USD_JPY
    FROM `client_cloudflare.stg_reddit`
    GROUP BY 2, 3, 4
),
line_jp AS (
    SELECT
        'LINE'                           AS CHANNEL,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        'JP'                             AS MARKET,
        SUM(IMPRESSIONS)                 AS IMPS,
        SUM(CLICKS)                      AS CLICKS,
        ROUND(SUM(COST) / 155.0, 2)      AS SPEND_USD,
        0                                AS LEADS,
        CAST(NULL AS FLOAT64)            AS FORM_OPENS,
        CAST(NULL AS FLOAT64)            AS LINK_CLICKS,
        CAST(NULL AS FLOAT64)            AS ACTION_CLICKS,
        SUM(VIDEO_STARTS)                AS VIDEO_STARTS,
        SUM(VIDEO_100_WATCHED)           AS VIDEO_COMPLETIONS,
        CAST(SUM(COST) AS FLOAT64)       AS SPEND_JPY,
        155.0                            AS FX_USD_JPY
    FROM `client_cloudflare.stg_line`
    GROUP BY 2, 3
)
SELECT * FROM linkedin
UNION ALL SELECT * FROM tradedesk
UNION ALL SELECT * FROM reddit
UNION ALL SELECT * FROM line_jp;
