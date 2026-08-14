-- stg_linkedin: Cloudflare's LinkedIn slice of the shared raw mirror.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINKEDIN_CF, now reading
-- the BigQuery mirror raw_snowflake.linkedin_ads_apac (landed by ingest/snowflake_data_pull)
-- instead of APAC_ALL_PLATFORM.PUBLIC."LinkedIn Ads - APAC" in Snowflake.
-- SELECT * keeps every column the downstream paid-media + creative views read.
--
-- 2026-08-04 - BRIEF-NUMBER PREFIX GUARD. CAMPAIGN_NAME here is LinkedIn's AD SET name
-- (LinkedIn's API "campaign" = an ad set; the parent is CAMPAIGN_GROUP_NAME). Ad-set
-- names have NOT been renamed yet, so this changes no number today - verified 3,746,467
-- imps / 16,908 clicks / 487 leads before and after. But the parent campaign names in
-- the media-buyer reference sheet ALREADY carry the prefix (2103_, 2413_, 2446_, 2479_),
-- and every downstream LinkedIn rule is a name match: STARTS_WITH(...,'CLOUD_ACQ_') plus
-- the '%apac-anz%'-style market CASE. If the rename reaches ad-set names, the
-- STARTS_WITH drops the whole channel to zero. Normalise once here and key the
-- downstream rules off CAMPAIGN_NAME_NORM so that cannot happen. Same treatment as
-- stg_tradedesk, where the equivalent break was already live.
--
-- PROGRAM (2026-08-14) - the dashboard's lane selector, kept IDENTICAL to
-- stg_tradedesk's arm so a campaign can never land in two lanes. LinkedIn has no
-- Surround ABM (brief 2193) delivery today - the brief is TTD-only - but carrying the
-- same rule here means an ad set that IS renamed into it routes to the right lane
-- instead of quietly inflating Core DG. Substring match on the RAW name (prefix-proof).
CREATE OR REPLACE VIEW `client_cloudflare.stg_linkedin` AS
SELECT
    *,
    REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM,
    CASE
        WHEN LOWER(IFNULL(CAMPAIGN_NAME, '')) LIKE '%surround%abm%'
          OR STARTS_WITH(TRIM(IFNULL(CAMPAIGN_NAME, '')), '2193_')
            THEN 'SURROUND_ABM'
        ELSE 'CORE_DG'
    END AS PROGRAM
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME = 'Cloudflare APAC';
