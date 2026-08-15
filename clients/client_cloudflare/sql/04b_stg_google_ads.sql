-- stg_google_ads: Cloudflare's Google Ads slice of the shared Snowflake mirror.
--
-- Added 2026-08-11 - Google Ads is the FIFTH paid channel on this dashboard (after TTD, LinkedIn,
-- Reddit and LINE). Transmission connected the `Cloudflare APAC` Google Ads account (ACCOUNT_ID
-- 3034487647) on ~2026-07-22; it feeds the Q3 Core DG book (brief 2479).
--
-- SCOPED BY ACCOUNT, NOT BY CAMPAIGN NAME - deliberately. The media sheet lists TWO Google Ads
-- lines against brief 2479 (Awareness from 15-Jul and Lead Generation from 17-Jul) but only the
-- Awareness one is in the mirror today. Filtering on the ACCOUNT means the Lead Generation campaign
-- starts reporting the moment Transmission connects it, with no code change here. It also keeps us
-- clear of the repo-wide "campaign names are NOT stable keys" trap - Google Ads campaign names here
-- do NOT follow the `CLOUD_ACQ_` convention the other channels use, so a name-based filter would be
-- both fragile and wrong.
--
-- PROGRAM: the same two-lane rule as stg_linkedin / stg_tradedesk, so a campaign can never land in
-- two lanes. There is no Surround ABM (brief 2193) Google Ads buy today - that brief is TTD-only -
-- but carrying the identical expression means a campaign renamed into it routes correctly instead
-- of quietly inflating Core DG.
--
-- CURRENCY: the account bills USD, which is already this dashboard's reporting currency, so there is
-- NO FX step (unlike LINE's JPY@155). The CASE is kept as a guard: if a non-USD Google Ads account
-- is ever added, it converts rather than silently mixing currencies into one SPEND_USD column.
--
-- KNOWN FEED GAP (flag to Transmission, do not paper over): the mirror carries no video columns
-- (no VIDEO_VIEWS / quartiles), and the live campaign is a YouTube VideoViews buy. Its real KPI is
-- therefore NOT in our data - impressions and clicks are all we can report, and the resulting ~0.05%
-- CTR is normal for video, not underperformance. The dashboard labels this channel as video /
-- awareness so the number is not read as a failure.
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
    AD_GROUP_NAME,
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
    CONVERSIONS_VIEWTHROUGH
FROM `bidbrain-analytics.raw_snowflake.google_ads_apac`
WHERE ACCOUNT_NAME = 'Cloudflare APAC';
