-- stg_tradedesk: Cloudflare's Trade Desk slice + the campaign-name parsing.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_TRADEDESK_CF, now reading
-- raw_snowflake.tradedesk_apac_all instead of APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL".
-- Snowflake -> BigQuery ports:
--   SPLIT_PART(name,'_',N)  -> SPLIT(name,'_')[SAFE_OFFSET(N-1)] (wrapped IFNULL '' to
--                              mirror Snowflake's empty-string-on-overflow, since the
--                              final model filters MARKET_L3 <> '' / IS NOT NULL).
--   ILIKE '%x%'             -> LOWER(col) LIKE '%x%'
--   COALESCE(IMPRESSIONS, IMPRESSION) keeps the singular-column fallback (see CLAUDE.md).
--
-- 2026-08-04 - BRIEF-NUMBER PREFIX FIX (this was silently losing ~34% of delivery).
-- Campaign names are progressively gaining a leading "<brief>_" token as briefs roll
-- out (1160_, 2103_, 2265_, 2479_ ...). Every token then shifts one position, so the
-- FIXED offsets below read the wrong field: MARKET_L3 came back as 'APAC-ANZ' instead
-- of 'ANZ', 'JAPAN-JPN' instead of 'JP', and so on. Those values are non-empty, so the
-- rows survived paid_media_model but matched no dashboard market chip and vanished from
-- every KPI, chart and table (4,989,809 imps / $14,672.73). The SAME campaign also
-- exists under both name forms in the feed, so the two halves never summed together.
-- FIX: strip the prefix ONCE into CAMPAIGN_NAME_NORM and parse every token off that.
-- (Raw CAMPAIGN_NAME is still carried through unchanged for display/debugging.)
-- This is the same normalisation the media-buyer reference sheet requires, and the same
-- defect AGENTS.md records as open for mongodb (2265_) and schneiderlqai (2306_).
CREATE OR REPLACE VIEW `client_cloudflare.stg_tradedesk` AS
WITH src AS (
    SELECT
        *,
        REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM
    FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
    WHERE ADVERTISER_NAME = 'Cloudflare'
)
SELECT
    DAY,
    ADVERTISER_NAME,
    CAMPAIGN_NAME,
    CAMPAIGN_NAME_NORM,
    AD_GROUP_NAME,
    CREATIVE_NAME,
    AD_TYPE      AS CREATIVE_FORMAT,
    PARTNER_NAME AS PUBLISHER,
    COALESCE(IMPRESSIONS, IMPRESSION)   AS IMPRESSIONS,
    COSTS,
    CLICKS,
    TOTAL_CLICK_PLUS_VIEW_CONVERSIONS   AS CONVERSIONS,
    COALESCE(
        -- normal long-form names: the market token is the 9th underscore field
        NULLIF(IFNULL(SPLIT(CAMPAIGN_NAME_NORM, '_')[SAFE_OFFSET(8)], ''), ''),
        -- short-form names carry no underscore market token and were dropped entirely
        -- by the `MARKET_L3 <> ''` filter downstream (DOOH / High Impact, 7,360,518
        -- imps / $29,699.60, Q2 May-Jun). They end in a " - AU" / " - NZ" / " - ANZ"
        -- suffix, so read that instead. Unknown suffixes still fall through to '' and
        -- are dropped exactly as before. Delete this arm to revert to the old scope.
        CASE UPPER(IFNULL(REGEXP_EXTRACT(CAMPAIGN_NAME_NORM, r'-\s*([A-Za-z]{2,3})\s*$'), ''))
            WHEN 'AU'  THEN 'ANZ'
            WHEN 'NZ'  THEN 'ANZ'
            WHEN 'ANZ' THEN 'ANZ'
            ELSE NULL
        END,
        ''
    ) AS MARKET_L3,
    IFNULL(SPLIT(CAMPAIGN_NAME_NORM, '_')[SAFE_OFFSET(9)],  '') AS FUNNEL_STAGE,
    IFNULL(SPLIT(CAMPAIGN_NAME_NORM, '_')[SAFE_OFFSET(12)], '') AS RAW_OBJECTIVE,
    CASE
        WHEN SPLIT(CAMPAIGN_NAME_NORM, '_')[SAFE_OFFSET(12)] = 'AWARENESS' THEN 'Awareness'
        ELSE 'Consideration'
    END AS FUNNEL_OBJECTIVE,
    CASE
        WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%retargeting%'
          OR LOWER(CAMPAIGN_NAME_NORM) LIKE '%rtg%'
            THEN 'Retargeting'
        ELSE 'Prospecting'
    END AS CAMPAIGN_TYPE
FROM src;
