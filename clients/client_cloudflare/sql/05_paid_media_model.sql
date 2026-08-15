-- paid_media_model: per-channel/market/day paid delivery for the dashboard.
-- BigQuery port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL:
-- a UNION ALL of the FIVE staging views with market derivation, weekly rollup key,
-- and JPY->USD@155 for LINE. Replaces the old thin pass-through of src_paid_media.
-- (Google Ads joined 2026-08-11 as the fifth channel - Q3 Core DG, brief 2479.)
-- Snowflake -> BigQuery ports:
--   DATE_TRUNC('WEEK', d)::DATE  -> DATE_TRUNC(d, WEEK(MONDAY))  (Snowflake weeks start Monday)
--   ILIKE '%x%'                  -> LOWER(col) LIKE '%x%'
--   LIKE 'CLOUD\_ACQ\_%' ESCAPE  -> STARTS_WITH(CAMPAIGN_NAME,'CLOUD_ACQ_')
-- Column/label contract (CHANNEL, MARKET strings) is unchanged from the dashboard's
-- expectations (TTD/LinkedIn/Reddit/LINE; the 7 L1 markets + raw TTD MARKET_L3).
--
-- 2026-08-14 - PROGRAM is the second column of EVERY arm (the union is `SELECT *`, so
-- position matters). It splits the paid book into the dashboard's two lanes:
--   CORE_DG      - Core DG APJ (briefs 1160 / 2103 Q2 / 2479 Q3), the default
--   SURROUND_ABM - Surround ABM (brief 2193, TTD-only; names say Q2, delivery spans Q2+Q3)
-- The rule lives in stg_tradedesk / stg_linkedin so both are literally the same
-- expression; Reddit repeats it inline (it has no staging view of its own) and LINE is
-- a constant (a manual LINE Ad Manager CSV with no campaign names - it is Core DG's JP
-- channel and there is no Surround ABM LINE buy).
CREATE OR REPLACE VIEW `client_cloudflare.paid_media_model` AS
WITH linkedin AS (
    SELECT
        'LinkedIn'                       AS CHANNEL,
        PROGRAM                          AS PROGRAM,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        -- Market rules key off CAMPAIGN_NAME_NORM (brief-number prefix stripped in
        -- stg_linkedin, 2026-08-04) so a "<brief>_" rename cannot break them.
        CASE
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-anz%'   THEN 'ANZ'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-asean%' THEN 'ASEAN'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-in%'    THEN 'SAARC'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-tcn%'   THEN 'GCR'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%_jp_%' OR LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-jp%' THEN 'JP'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%_kr_%' OR LOWER(CAMPAIGN_NAME_NORM) LIKE '%apac-kr%' THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%rig%'        THEN 'RIG'
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
    WHERE STARTS_WITH(CAMPAIGN_NAME_NORM, 'CLOUD_ACQ_')
    GROUP BY 2, 3, 4, 5
),
tradedesk AS (
    SELECT
        'TTD'                            AS CHANNEL,
        PROGRAM                          AS PROGRAM,
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
    GROUP BY 2, 3, 4, 5
),
reddit AS (
    SELECT
        'Reddit'                         AS CHANNEL,
        CASE
            WHEN LOWER(IFNULL(CAMPAIGN_NAME, '')) LIKE '%surround%abm%'
              OR STARTS_WITH(TRIM(IFNULL(CAMPAIGN_NAME, '')), '2193_')
                THEN 'SURROUND_ABM'
            ELSE 'CORE_DG'
        END                              AS PROGRAM,
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
    GROUP BY 2, 3, 4, 5
),
google_ads AS (
    -- Added 2026-08-11. Market is parsed from the campaign name with the SAME token rules the
    -- other channels use (the live buy is `CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting`, whose
    -- `_JP_` token resolves to JP). Google Ads has no lead-form or video columns in this mirror,
    -- so those slots are NULL - NOT 0 - which lets the dashboard hide them rather than draw a
    -- false zero. See 04b_stg_google_ads.sql for the feed gap on YouTube video metrics.
    SELECT
        'Google Ads'                     AS CHANNEL,
        PROGRAM                          AS PROGRAM,
        DAY                              AS DATE,
        DATE_TRUNC(DAY, WEEK(MONDAY))    AS WEEK_START,
        -- DELIMITER-AWARE REGEX, NOT `LIKE '%_xx_%'`. In SQL LIKE, `_` is a SINGLE-CHARACTER
        -- WILDCARD, not a literal underscore - so '%_in_%' matches "prospecTINGg"-style text and
        -- this campaign (CF_JP_Q3_TOFU_YouTube_VideoViews_Prospecting) was resolving to SAARC
        -- instead of JP on its first deploy (caught in QA 2026-08-11). The country codes here are
        -- 2-3 letters, so a bare LIKE is never safe for them; use the same boundary-anchored
        -- REGEXP_CONTAINS that client_schneider's parsers use. The `apac-xx` forms carry a hyphen
        -- and are matched as plain substrings, which is safe.
        CASE
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-anz')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])anz([ _-]|$)') THEN 'ANZ'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-asean')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])asean([ _-]|$)') THEN 'ASEAN'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-jp')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])(jp|japan)([ _-]|$)') THEN 'JP'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-kr')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])(kr|korea)([ _-]|$)') THEN 'KR'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-tcn')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])(tw|hk|cn|gcr)([ _-]|$)') THEN 'GCR'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-in')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])(in|india|saarc)([ _-]|$)') THEN 'SAARC'
            WHEN REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])rig([ _-]|$)') THEN 'RIG'
            ELSE 'UNMAPPED'
        END                              AS MARKET,
        SUM(IMPRESSIONS)                 AS IMPS,
        SUM(CLICKS)                      AS CLICKS,
        SUM(COSTS)                       AS SPEND_USD,
        CAST(NULL AS FLOAT64)            AS LEADS,
        CAST(NULL AS FLOAT64)            AS FORM_OPENS,
        CAST(NULL AS FLOAT64)            AS LINK_CLICKS,
        CAST(NULL AS FLOAT64)            AS ACTION_CLICKS,
        CAST(NULL AS FLOAT64)            AS VIDEO_STARTS,
        CAST(NULL AS FLOAT64)            AS VIDEO_COMPLETIONS,
        CAST(NULL AS FLOAT64)            AS SPEND_JPY,
        CAST(NULL AS FLOAT64)            AS FX_USD_JPY
    FROM `client_cloudflare.stg_google_ads`
    GROUP BY 2, 3, 4, 5
),
line_jp AS (
    SELECT
        'LINE'                           AS CHANNEL,
        'CORE_DG'                        AS PROGRAM,
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
    GROUP BY 3, 4
)
SELECT * FROM linkedin
UNION ALL SELECT * FROM tradedesk
UNION ALL SELECT * FROM reddit
UNION ALL SELECT * FROM google_ads
UNION ALL SELECT * FROM line_jp;
