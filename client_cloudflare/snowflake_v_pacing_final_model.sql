-- ============================================================================
-- MANUAL SNOWFLAKE DDL -- run by a role with OWNERSHIP on
--   CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL  (client/Transmission
--   owning role, or ACCOUNTADMIN). NOT applied by create_views.py (BigQuery).
--
-- FIX (2026-06-10): the lead de-dup partitioned by COALESCE(EMAIL, LEAD_ID_SF).
-- Its real job is to collapse the V_TIER_MAPPING_CLEANED LEFT-JOIN fan-out to
-- one row per lead -- but keying on EMAIL also merged DISTINCT Salesforce leads
-- that share an email, undercounting vs the canonical
-- APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL" totals (accepted 3199->3176,
-- rejected 383->346). LEAD_ID_SF is unique per lead (3582 rows, 3582 distinct,
-- 0 null), so the key is changed to COALESCE(LEAD_ID_SF, EMAIL): fan-out still
-- collapses, distinct leads are preserved. This is the ONLY change vs the live
-- definition (generated from GET_DDL); columns / allocation / dummy rows intact.
--
-- NOTE: V_PACING_FINAL_MODEL is shared; any other consumer (e.g. DAILY_* tasks
-- that COPY INTO R2) will also pick up the corrected per-lead counts.
-- ============================================================================
create or replace view CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL(
	DT_CREATED,
	DT_UPDATED,
	DT_FILENAME,
	DAY,
	FIRST_NAME,
	LAST_NAME,
	EMAIL,
	COMPANY_NAME,
	JOB_TITLE,
	JOB_FUNCTION,
	JOB_LEVEL,
	OPT_IN,
	ASSET_1,
	ASSET_2,
	CAMPAIGN,
	PHONE,
	INDUSTRY_NAME,
	WEBSITE,
	STATE,
	REGION,
	COUNTRY_NAME,
	ANNUAL_REVENUE_,
	CAMPAIGN_ID,
	LEADS,
	LEAD_ID_SF,
	STATUS,
	LEAD_STATUS,
	PUBLISHER,
	OFFER_TYPE,
	PUBLISHER_OFFER,
	L2,
	MARKET_REGION,
	RIG,
	TIER,
	SERVICE,
	LEAD_VALUE,
	ANZ,
	ASEAN,
	SAARC,
	GCR,
	KR,
	JP,
	ALLOCATED_TARGET,
	CUMULATIVE_ACTUAL,
	CUMULATIVE_TARGET
) as

WITH
-- ============================================================
-- A. LEADS WITH TIERS  (inlined from V_LEADS_WITH_TIERS)
-- ============================================================

-- A1. Clean company name into a fuzzy join key
lead_prep AS (
    SELECT 
        *,
        LOWER(REGEXP_REPLACE(
            TRIM(COMPANY_NAME),
            '( pty| ltd| inc| corp| limited| pte| corporation| co| ltd\\.)$',
            '', 1, 0, 'i'
        )) AS JOIN_KEY_LEAD
    FROM CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE
),

-- A2. Join tier mapping + derive L2_STANDARD, MARKET_REGION, RIG flag
tiered_leads AS (
    SELECT 
        lp.*,
        CASE WHEN lp.REGION_GRP = 'SAARC' THEN 'IN' ELSE lp.REGION_GRP END AS L2_STANDARD,

        -- MARKET_REGION: override to 'RIG' for Computer Games + Tier 2 leads
        CASE 
            WHEN lp.INDUSTRY_NAME = 'Computer Games' 
                 AND COALESCE(t.CLEAN_TIER, 'Other') = 'Tier 2' 
            THEN 'RIG'
            ELSE lp.REGION_GRP
        END                                                               AS MARKET_REGION,

        COALESCE(t.CLEAN_TIER, 'Other')                                   AS FINAL_TIER,
        t.L1                                                              AS TIER_L1,

        -- RIG flag: L1='RIG' OR (Computer Games + Tier 2)
        CASE 
            WHEN UPPER(TRIM(t.L1)) = 'RIG' THEN 1 
            WHEN lp.INDUSTRY_NAME = 'Computer Games' 
                 AND COALESCE(t.CLEAN_TIER, 'Other') = 'Tier 2' THEN 1
            ELSE 0 
        END                                                               AS RIG
    FROM lead_prep lp
    LEFT JOIN CLOUDFLARE_SANDBOX.CS_REPORTING.V_TIER_MAPPING_CLEANED t 
        ON lp.JOIN_KEY_LEAD = t.JOIN_NAME
),

-- ============================================================
-- B. PACING MODEL
--    NOTE: filter changed from 'Passed' -> 'Accepted' (May 2026)
-- ============================================================

-- B1. De-duplicate leads
processed_leads AS (
    SELECT *
    FROM tiered_leads
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(LEAD_ID_SF, EMAIL)
        ORDER BY DAY ASC, DT_CREATED ASC
    ) = 1
),

-- B2. Join targets, compute per-lead allocations
leads_allocated AS (
    SELECT 
        a.DT_CREATED, a.DT_UPDATED, a.DT_FILENAME, a.DAY, a.FIRST_NAME, a.LAST_NAME, 
        a.EMAIL, a.COMPANY_NAME, a.JOB_TITLE, a.JOB_FUNCTION, a.JOB_LEVEL, a.OPT_IN, 
        a.ASSET_1, a.ASSET_2, a.CAMPAIGN, a.PHONE, a.INDUSTRY_NAME, a.WEBSITE, 
        a.STATE, a.REGION, a.COUNTRY_NAME, a.ANNUAL_REVENUE_, a.CAMPAIGN_ID, 
        a.LEADS, a.LEAD_ID_SF, a.STATUS, a.LEAD_STATUS,
        a.PUBLISHER, a.OFFER_TYPE, a.PUBLISHER_OFFER,
        
        a.L2_STANDARD                              AS L2,
        a.MARKET_REGION                            AS MARKET_REGION,
        a.RIG                                      AS RIG,
        COALESCE(a.FINAL_TIER, 'Other')            AS TIER,
        
        CASE 
            WHEN a.CAMPAIGN ILIKE '%Connectivity%Cloud%'  THEN 'Connectivity Cloud'
            WHEN a.CAMPAIGN ILIKE '%Modernize%Network%'   THEN 'Modernized Networks'
            WHEN a.CAMPAIGN ILIKE '%Modernize%Security%'  THEN 'Modernized Security'
            WHEN a.CAMPAIGN ILIKE '%Modernize%App%'       THEN 'Modernized Applications'
            ELSE 'Unknown'
        END AS SERVICE,
        
        CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS LEAD_VALUE, 
        
        -- Per-region flags: 1 only when MARKET_REGION matches AND lead is Accepted
        CASE WHEN a.MARKET_REGION = 'ANZ'   AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS ANZ,
        CASE WHEN a.MARKET_REGION = 'ASEAN' AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS ASEAN,
        CASE WHEN a.MARKET_REGION = 'SAARC' AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS SAARC,
        CASE WHEN a.MARKET_REGION = 'GCR'   AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS GCR,
        CASE WHEN a.MARKET_REGION = 'KR'    AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS KR,
        CASE WHEN a.MARKET_REGION = 'JP'    AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS JP,
        
        -- Spread cell's target evenly across Accepted leads in that cell
        CASE 
            WHEN a.LEAD_STATUS = 'Accepted' THEN 
                COALESCE(
                    t.WEEKLY_TIER_TARGET 
                    / NULLIF(SUM(CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END) 
                             OVER (PARTITION BY TRUNC(a.DAY, 'WEEK'),
                                                a.MARKET_REGION, 
                                                COALESCE(a.FINAL_TIER, 'Other')), 0),
                    0
                )
            ELSE 0 
        END AS ALLOCATED_TARGET
        
    FROM processed_leads a
    LEFT JOIN CLOUDFLARE_SANDBOX.CS_REPORTING.V_TARGETS_V2_NORM t 
        ON TRUNC(a.DAY, 'WEEK')                = t.WEEK_START
       AND a.MARKET_REGION                     = t.MARKET_REGION
       AND COALESCE(a.FINAL_TIER, 'Other')     = t.TIER
),

-- B3. Count Accepted leads consumed per (week, region, tier) cell
target_consumed AS (
    SELECT 
        TRUNC(a.DAY, 'WEEK')                       AS WEEK_START,
        a.MARKET_REGION                            AS MARKET_REGION,
        COALESCE(a.FINAL_TIER, 'Other')            AS TIER,
        SUM(CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END) AS ACCEPTED_COUNT
    FROM processed_leads a
    GROUP BY 1, 2, 3
),

-- B4. Cells that have remaining (unconsumed) target
target_remaining AS (
    SELECT 
        t.WEEK_START,
        t.MARKET_REGION,
        t.TIER,
        t.WEEKLY_TIER_TARGET,
        CASE 
            WHEN COALESCE(c.ACCEPTED_COUNT, 0) = 0 THEN t.WEEKLY_TIER_TARGET 
            ELSE 0 
        END AS REMAINING_TARGET
    FROM CLOUDFLARE_SANDBOX.CS_REPORTING.V_TARGETS_V2_NORM t
    LEFT JOIN target_consumed c 
        ON t.WEEK_START     = c.WEEK_START
       AND t.MARKET_REGION  = c.MARKET_REGION
       AND t.TIER           = c.TIER
    WHERE t.WEEKLY_TIER_TARGET > 0
),

-- B5. Dummy placeholder rows for cells still carrying remaining target
dummy_rows AS (
    SELECT 
        NULL AS DT_CREATED, NULL AS DT_UPDATED, NULL AS DT_FILENAME, 
        r.WEEK_START AS DAY, 
        NULL AS FIRST_NAME, NULL AS LAST_NAME, NULL AS EMAIL, NULL AS COMPANY_NAME, 
        NULL AS JOB_TITLE, NULL AS JOB_FUNCTION, NULL AS JOB_LEVEL, NULL AS OPT_IN, 
        NULL AS ASSET_1, NULL AS ASSET_2, NULL AS CAMPAIGN, NULL AS PHONE, 
        NULL AS INDUSTRY_NAME, NULL AS WEBSITE, 
        NULL AS STATE, r.MARKET_REGION AS REGION, NULL AS COUNTRY_NAME, 
        NULL AS ANNUAL_REVENUE_, NULL AS CAMPAIGN_ID, 
        NULL AS LEADS, 'DUMMY_' || UUID_STRING() AS LEAD_ID_SF, 
        'Accepted' AS STATUS, NULL AS LEAD_STATUS,
        NULL AS PUBLISHER, NULL AS OFFER_TYPE, NULL AS PUBLISHER_OFFER,
        
        NULL                       AS L2,
        r.MARKET_REGION            AS MARKET_REGION,
        0                          AS RIG,
        r.TIER                     AS TIER,
        NULL                       AS SERVICE,
        0                          AS LEAD_VALUE,
        
        0 AS ANZ, 0 AS ASEAN, 0 AS SAARC, 0 AS GCR, 0 AS KR, 0 AS JP,
        
        r.REMAINING_TARGET         AS ALLOCATED_TARGET
        
    FROM target_remaining r
    WHERE r.REMAINING_TARGET > 0
),

-- B6. Union real leads + dummies
combined AS (
    SELECT * FROM leads_allocated
    UNION ALL
    SELECT * FROM dummy_rows
)

SELECT 
    *,
    SUM(LEAD_VALUE)        OVER (PARTITION BY MARKET_REGION, TIER ORDER BY TRUNC(DAY, 'WEEK')) AS CUMULATIVE_ACTUAL,
    SUM(ALLOCATED_TARGET)  OVER (PARTITION BY MARKET_REGION, TIER ORDER BY TRUNC(DAY, 'WEEK')) AS CUMULATIVE_TARGET
FROM combined;;
