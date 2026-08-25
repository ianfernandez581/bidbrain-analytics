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
--
-- 2026-08-26 - carries FORM_OPENS on the LinkedIn arm, for the "LinkedIn creative lead
-- efficiency" tables (top 10 by CPL / by click->lead CVR; client request). LEADS was already
-- here, so CPL and CVR were derivable - but not DIAGNOSABLE: a low CVR because nobody opens
-- the form is a targeting/creative problem, one where they open and abandon is a form problem,
-- and without the middle stage the two are indistinguishable. Same stage the channel-level
-- LinkedIn funnel already shows (LEAD_FORM_OPENS / oneClickLeadFormOpens on datastream 924),
-- now at creative grain so the funnel's CPL and click->lead rate break down to the row that
-- earned them. Verified against paid_media_model: LinkedIn ties EXACTLY on all four measures
-- (590 leads / 6,779 form opens / 21,149 clicks / $153,281.15), so a creative table total can
-- never disagree with the funnel above it.
-- NULL, not 0, on the four channels that have no lead form at all - a false zero would read as
-- "nobody opened the form" rather than "this channel has no form" if the column is ever
-- surfaced beyond the LinkedIn-only tables (the repo-wide rule; cf. the Google Ads video
-- columns in paid_media_model).
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
            -- Boundary-anchored, NOT `LIKE '%_jp_%'`: `_` is a single-character WILDCARD in LIKE, so
            -- that form also matches any-char+jp+any-char inside an ordinary word. Harmless while the
            -- apac-xx arms above catch every current name, but it is a live trap for a campaign named
            -- without an APAC-xx token - exactly how the Google Ads arm sent JP delivery to SAARC
            -- (2026-08-11). Hardened 2026-08-15; verified a no-op against the current LinkedIn book.
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-jp')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])jp([ _-]|$)') THEN 'JP'
            WHEN CONTAINS_SUBSTR(LOWER(CAMPAIGN_NAME_NORM), 'apac-kr')
              OR REGEXP_CONTAINS(LOWER(CAMPAIGN_NAME_NORM), r'(^|[ _-])kr([ _-]|$)') THEN 'KR'
            WHEN LOWER(CAMPAIGN_NAME_NORM) LIKE '%rig%'        THEN 'RIG'
            ELSE 'UNMAPPED'
        END AS MARKET,
        COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), NULLIF(TRIM(AD_TITLE), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, SUM(LEADS) AS LEADS,
        -- Lead-form starts. IFNULL around the SUM (not inside): SUM ignores NULL rows and only
        -- returns NULL when EVERY row is NULL, which is a creative that genuinely has no form
        -- data rather than one with zero starts - report that as 0 for a lead-gen ad set.
        IFNULL(SUM(LEAD_FORM_OPENS), 0) AS FORM_OPENS
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
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS,
        CAST(NULL AS FLOAT64) AS FORM_OPENS
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
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS,
        CAST(NULL AS FLOAT64) AS FORM_OPENS
    FROM `client_cloudflare.stg_reddit`
    GROUP BY 2, 3, 4
),
google_ads AS (
    -- Added 2026-08-11. Google Ads has no creative-name column in this mirror, so we show the
    -- finest grain the feed carries. That WAS the ad group (`TOFU | Persona` vs `TOFU | Custom
    -- Intent`) until 2026-08-20, when Transmission moved the shared export to CAMPAIGN level for
    -- the Performance Max lead-gen buy and AD_GROUP_NAME disappeared (see stg_google_ads' header).
    -- NETWORK is what replaced it, and for a PMax campaign it is the more useful cut anyway -
    -- every conversion so far came from DISCOVER while CONTENT produced none.
    -- THERE IS NO REAL CREATIVE DATA FOR THIS CHANNEL ANYWHERE (checked 2026-08-20): the Snowflake
    -- mirror is campaign-grain with no ad columns, the native DTS MCC 3451896252 does not carry
    -- account 3034487647, and raw_windsor.perf_google_ads has no creative field at all and no
    -- Cloudflare rows. Getting real creatives needs Transmission to add ad / asset-level columns
    -- (ad name + asset for PMax, video asset for the YouTube buy). Until then this is the floor,
    -- not a design choice - do not swap in something that merely looks like a creative name.
    -- Market rules mirror paid_media_model's Google Ads arm.
    SELECT
        'Google Ads' AS CHANNEL,
        PROGRAM AS PROGRAM,
        -- Boundary-anchored regex, NOT `LIKE '%_xx_%'` - `_` is a single-character WILDCARD in LIKE,
        -- which sent this campaign to SAARC instead of JP on first deploy. Keep IDENTICAL to
        -- paid_media_model's Google Ads arm or the creative table will disagree with the KPIs.
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
        END AS MARKET,
        -- CAMPAIGN x NETWORK. Network alone merged BOTH campaigns' YouTube delivery into one
        -- row (the TOFU VideoViews buy and PMax's YouTube placements are not the same thing),
        -- so the campaign has to be on the label for the row to mean anything.
        CONCAT(CAMPAIGN_NAME_NORM, ' - ',
               INITCAP(REPLACE(COALESCE(NETWORK, 'UNKNOWN'), '_', ' '))) AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS, SUM(COSTS) AS SPEND_USD, 0 AS LEADS,
        CAST(NULL AS FLOAT64) AS FORM_OPENS
    FROM `client_cloudflare.stg_google_ads`
    GROUP BY 2, 3, 4
),
line_jp AS (
    SELECT
        'LINE' AS CHANNEL,
        'CORE_DG' AS PROGRAM,
        'JP' AS MARKET,
        COALESCE(NULLIF(TRIM(AD_NAME), ''), '(unnamed)') AS CREATIVE,
        SUM(IMPRESSIONS) AS IMPS, SUM(CLICKS) AS CLICKS,
        ROUND(SUM(COST) / 155.0, 2) AS SPEND_USD, 0 AS LEADS,
        CAST(NULL AS FLOAT64) AS FORM_OPENS
    FROM `client_cloudflare.stg_line`
    GROUP BY 4
)
SELECT CHANNEL, PROGRAM, MARKET, CREATIVE, IMPS, CLICKS, SPEND_USD, LEADS, FORM_OPENS
FROM (
    SELECT * FROM linkedin
    UNION ALL SELECT * FROM tradedesk
    UNION ALL SELECT * FROM reddit
    UNION ALL SELECT * FROM google_ads
    UNION ALL SELECT * FROM line_jp
)
WHERE IMPS > 0;
