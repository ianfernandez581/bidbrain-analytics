-- stg_google_ads: Cloudflare's Google Ads slice of the shared Snowflake mirror.
--
-- Added 2026-08-11 - Google Ads is the FIFTH paid channel on this dashboard (after TTD, LinkedIn,
-- Reddit and LINE). Transmission connected the `Cloudflare APAC` Google Ads account (ACCOUNT_ID
-- 3034487647) on ~2026-07-22; it feeds the Q3 Core DG book (brief 2479).
--
-- SCOPED BY ACCOUNT, NOT BY CAMPAIGN NAME - deliberately. The media sheet lists TWO Google Ads
-- lines against brief 2479 (Awareness from 15-Jul and Lead Generation from 17-Jul). The account
-- filter is what let the Lead Generation campaign start reporting on 2026-08-06 with no change to
-- this WHERE clause. It also keeps us clear of the repo-wide "campaign names are NOT stable keys"
-- trap - Google Ads campaign names here do NOT follow the `CLOUD_ACQ_` convention the other
-- channels use, so a name-based filter would be both fragile and wrong.
--
-- ============================================================================================
-- GRAIN CHANGED 2026-08-20 - AD_GROUP_NAME IS GONE, `NETWORK` ARRIVED
-- ============================================================================================
-- Transmission (Ankit) moved the shared `Google Ads - APAC` export from AD GROUP level to
-- CAMPAIGN level, because the new Lead Generation campaign is **Performance Max** and PMax
-- reports nothing at ad-group grain. The mirror is a `SELECT *` WRITE_TRUNCATE copy
-- (ingest/snowflake_data_pull/loader.py), so the new schema landed on the next */10 tick with no
-- warning and `AD_GROUP_NAME` simply vanished - which broke THIS view, and through it
-- paid_media_model + paid_creatives_model + every cloudflare-export run, for ~19 hours.
-- (STT reads the same mirror but not the ad group, so it was unaffected.)
--
-- The row grain is now DAY x CAMPAIGN x **NETWORK** (YOUTUBE / DISCOVER / CONTENT / SEARCH /
-- SEARCH_PARTNERS / MIXED). NETWORK is carried through as a real dimension: it is the only
-- sub-campaign cut the feed still has, and for the PMax buy it is the genuinely actionable one
-- (every conversion so far is DISCOVER; CONTENT has produced none).
-- Delivery reconciled across the grain change with no loss - the Awareness campaign's
-- 2026-07-22..08-08 window reads 172,332 imps / 90 clicks / $764.83 against the 172,396 / 90 /
-- $765.16 recorded at build time (a 0.04% Google restatement, not a data change).
--
-- ============================================================================================
-- VIDEO METRICS ARE **RATES**, NOT COUNTS - converted to counts here
-- ============================================================================================
-- The same 2026-08-20 change added the video columns we had been asking for. They do NOT arrive
-- as counts: VIDEO_PLAYED_TO_50 / _75 and VIEW_RATE_IN_STREAM / TRUEVIEW_VIEW_RATE are FLOAT
-- RATES in 0..1 (Google's `video_quartile_pXX_rate` / `video_view_rate`, all denominated in
-- IMPRESSIONS). A rate must never reach a fact table that gets SUM()ed - so each one is
-- multiplied back out to a COUNT here, at source-row grain, where its own impressions are the
-- correct denominator. Every downstream rollup is then exact, and any consumer can re-derive the
-- rate as count / impressions. NEVER SUM the raw rate columns.
--
-- TWO OF THE FIVE NEW COLUMNS ARE DEAD ON ARRIVAL - flag to Transmission, do not paper over:
--   * `VIDEO_PLAYED_TO_25_` - 100% NULL across every row. Note the STRAY TRAILING UNDERSCORE in
--     the column name, which is itself a source-side header bug. Not referenced here.
--   * `VIDEO_PLAYED_TO_100`  - literally 0.0 on every row. It cannot be real: 67% of impressions
--     reach the 75% quartile, so a 0% completion rate is a broken field, not a finding. Not
--     referenced here - carrying it would draw a "0 completions" that reads as failure.
-- So there is still NO true completion metric, and still no native view COUNT. What we DO now
-- have is the campaign's real KPI: 176,429 in-stream views on 275,598 impressions = a 64.0% view
-- rate at $0.0069 CPV, which is the number that reframes the 0.05% CTR nobody should have been
-- reading as underperformance.
--
-- CURRENCY: the account bills USD, which is already this dashboard's reporting currency, so there
-- is NO FX step (unlike LINE's JPY@155). The CASE is kept as a guard: if a non-USD Google Ads
-- account is ever added, it converts rather than silently mixing currencies into one column.
CREATE OR REPLACE VIEW `client_cloudflare.stg_google_ads` AS
SELECT
    DATE(DAY)                                AS DAY,
    ACCOUNT_NAME,
    ACCOUNT_ID,
    CAMPAIGN_NAME,
    CAMPAIGN_ID,
    -- Prefix-proof normalisation, matching the other staging views. Google Ads names carry no
    -- brief-number prefix today; this keeps every channel's parsing rules interchangeable.
    REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM,
    -- Replaces AD_GROUP_NAME as the finest available grain (see the header note).
    NULLIF(TRIM(IFNULL(NETWORK, '')), '')    AS NETWORK,
    CASE
        WHEN LOWER(IFNULL(CAMPAIGN_NAME, '')) LIKE '%surround%abm%'
          OR STARTS_WITH(TRIM(IFNULL(CAMPAIGN_NAME, '')), '2193_')
            THEN 'SURROUND_ABM'
        ELSE 'CORE_DG'
    END                                      AS PROGRAM,
    IMPRESSIONS                              AS IMPRESSIONS,
    CLICKS                                   AS CLICKS,
    CASE CURRENCY
        WHEN 'USD' THEN COSTS
        WHEN 'JPY' THEN COSTS / 155.0
        WHEN 'AUD' THEN COSTS / 1.50
        ELSE COSTS
    END                                      AS COSTS,
    CURRENCY,
    CONVERSIONS,
    CONVERSIONS_VIEWTHROUGH,
    -- Rates -> counts (see header). NULL rate stays NULL, so a channel/day with no video
    -- delivery reports "no data" rather than a false zero.
    VIEW_RATE_IN_STREAM  * IMPRESSIONS       AS VIDEO_VIEWS,
    VIDEO_PLAYED_TO_50   * IMPRESSIONS       AS VIDEO_Q50,
    VIDEO_PLAYED_TO_75   * IMPRESSIONS       AS VIDEO_Q75
FROM `bidbrain-analytics.raw_snowflake.google_ads_apac`
WHERE ACCOUNT_NAME = 'Cloudflare APAC';
