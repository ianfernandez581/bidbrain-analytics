-- pacing_model: Content-Syndication lead pacing for the dashboard (pacing.rows).
-- BigQuery port of CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL. Reads the BQ
-- views salesforce_leads_live + tier_mapping_cleaned + targets_v2_norm (all modelled in
-- BigQuery now). Emits every column the dashboard reads, byte-compatible with the old
-- Snowflake passthrough.
-- Snowflake -> BigQuery ports:
--   TRUNC(d,'WEEK') / DATE_TRUNC('WEEK',d) -> DATE_TRUNC(d, WEEK(MONDAY))  (Snowflake weeks = Monday)
--   REGEXP_REPLACE(...,1,0,'i')            -> RE2 (?i) inline flag
--   ILIKE '%x%'                            -> LOWER(col) LIKE '%x%'
--   'DUMMY_' || UUID_STRING()              -> CONCAT('DUMMY_', GENERATE_UUID())
--   QUALIFY ROW_NUMBER()...                -> QUALIFY (supported natively)
CREATE OR REPLACE VIEW `client_cloudflare.pacing_model` AS
WITH
-- A1. Clean company name into a fuzzy join key (identical regex to tier_mapping_cleaned.JOIN_NAME)
lead_prep AS (
    SELECT
        *,
        LOWER(REGEXP_REPLACE(TRIM(COMPANY_NAME),
            r'(?i)( pty| ltd| inc| corp| limited| pte| corporation| co| ltd\.)$', '')) AS JOIN_KEY_LEAD
    FROM `client_cloudflare.salesforce_leads_live`
),

-- A2. Join tier mapping + derive L2_STANDARD, MARKET_REGION, RIG flag.
-- MARKET_REGION = REGION_GRP verbatim. RIG and KR are now CLIENT-DEFINED in
-- salesforce_leads_live.REGION_GRP (see sql/10): RIG = the Modernize-Applications asset on the 3
-- Final Funnel campaigns (non-Korea), KR = Korea on the 6 El* campaigns. The OLD "Computer Games +
-- Tier 2 -> RIG" geographic override is REMOVED — keeping it would re-route additional leads into
-- RIG and break the exact 180-lead client definition (RIG must equal sql/10's REGION_GRP='RIG').
tiered_leads AS (
    SELECT
        lp.*,
        CASE WHEN lp.REGION_GRP = 'SAARC' THEN 'IN' ELSE lp.REGION_GRP END AS L2_STANDARD,
        lp.REGION_GRP AS MARKET_REGION,
        COALESCE(t.CLEAN_TIER, 'Other') AS FINAL_TIER,
        t.L1 AS TIER_L1,
        CASE WHEN lp.REGION_GRP = 'RIG' THEN 1 ELSE 0 END AS RIG
    FROM lead_prep lp
    LEFT JOIN `client_cloudflare.tier_mapping_cleaned` t
        ON lp.JOIN_KEY_LEAD = t.JOIN_NAME
),

-- B1. De-duplicate leads (one row per lead; LEAD_ID_SF is unique so this is a no-op for real leads)
processed_leads AS (
    SELECT *
    FROM tiered_leads
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY COALESCE(LEAD_ID_SF, EMAIL)
        ORDER BY DAY ASC, DT_CREATED ASC
    ) = 1
),

-- B2. Join weekly targets; compute per-lead allocations (spread a cell's target across its Accepted leads)
leads_allocated AS (
    SELECT
        a.DT_CREATED, a.DT_UPDATED, a.DT_FILENAME, a.DAY, a.FIRST_NAME, a.LAST_NAME,
        a.EMAIL, a.COMPANY_NAME, a.JOB_TITLE, a.JOB_FUNCTION, a.JOB_LEVEL, a.OPT_IN,
        a.ASSET_1, a.ASSET_2, a.CAMPAIGN, a.PHONE, a.INDUSTRY_NAME, a.WEBSITE,
        a.STATE, a.REGION, a.COUNTRY_NAME, a.ANNUAL_REVENUE_, a.CAMPAIGN_ID,
        a.LEADS, a.LEAD_ID_SF, a.STATUS, a.LEAD_STATUS,
        a.PUBLISHER, a.OFFER_TYPE, a.PUBLISHER_OFFER,

        a.L2_STANDARD                           AS L2,
        a.MARKET_REGION                         AS MARKET_REGION,
        a.RIG                                   AS RIG,
        COALESCE(a.FINAL_TIER, 'Other')         AS TIER,

        CASE
            WHEN LOWER(a.CAMPAIGN) LIKE '%connectivity%cloud%'  THEN 'Connectivity Cloud'
            WHEN LOWER(a.CAMPAIGN) LIKE '%modernize%network%'   THEN 'Modernized Networks'
            WHEN LOWER(a.CAMPAIGN) LIKE '%modernize%security%'  THEN 'Modernized Security'
            WHEN LOWER(a.CAMPAIGN) LIKE '%modernize%app%'       THEN 'Modernized Applications'
            ELSE 'Unknown'
        END AS SERVICE,

        CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS LEAD_VALUE,

        CASE WHEN a.MARKET_REGION = 'ANZ'   AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS ANZ,
        CASE WHEN a.MARKET_REGION = 'ASEAN' AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS ASEAN,
        CASE WHEN a.MARKET_REGION = 'SAARC' AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS SAARC,
        CASE WHEN a.MARKET_REGION = 'GCR'   AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS GCR,
        CASE WHEN a.MARKET_REGION = 'KR'    AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS KR,
        CASE WHEN a.MARKET_REGION = 'JP'    AND a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END AS JP,

        CASE
            WHEN a.LEAD_STATUS = 'Accepted' THEN
                COALESCE(
                    t.WEEKLY_TIER_TARGET
                    / NULLIF(SUM(CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END)
                             OVER (PARTITION BY DATE_TRUNC(a.DAY, WEEK(MONDAY)),
                                                a.MARKET_REGION,
                                                COALESCE(a.FINAL_TIER, 'Other')), 0),
                    0)
            ELSE 0
        END AS ALLOCATED_TARGET
    FROM processed_leads a
    LEFT JOIN `client_cloudflare.targets_v2_norm` t
        ON DATE_TRUNC(a.DAY, WEEK(MONDAY))    = t.WEEK_START
       AND a.MARKET_REGION                    = t.MARKET_REGION
       AND COALESCE(a.FINAL_TIER, 'Other')    = t.TIER
),

-- B3. Accepted leads consumed per (week, region, tier) cell
target_consumed AS (
    SELECT
        DATE_TRUNC(a.DAY, WEEK(MONDAY))         AS WEEK_START,
        a.MARKET_REGION                         AS MARKET_REGION,
        COALESCE(a.FINAL_TIER, 'Other')         AS TIER,
        SUM(CASE WHEN a.LEAD_STATUS = 'Accepted' THEN 1 ELSE 0 END) AS ACCEPTED_COUNT
    FROM processed_leads a
    GROUP BY 1, 2, 3
),

-- B4. Cells with remaining (unconsumed) target
target_remaining AS (
    SELECT
        t.WEEK_START,
        t.MARKET_REGION,
        t.TIER,
        t.WEEKLY_TIER_TARGET,
        CASE WHEN COALESCE(c.ACCEPTED_COUNT, 0) = 0 THEN t.WEEKLY_TIER_TARGET ELSE 0 END AS REMAINING_TARGET
    FROM `client_cloudflare.targets_v2_norm` t
    LEFT JOIN target_consumed c
        ON t.WEEK_START    = c.WEEK_START
       AND t.MARKET_REGION = c.MARKET_REGION
       AND t.TIER          = c.TIER
    WHERE t.WEEKLY_TIER_TARGET > 0
),

-- B5. Dummy placeholder rows carrying remaining target for empty cells
dummy_rows AS (
    SELECT
        CAST(NULL AS INT64) AS DT_CREATED, CAST(NULL AS INT64) AS DT_UPDATED,
        CAST(NULL AS STRING) AS DT_FILENAME,
        r.WEEK_START AS DAY,
        CAST(NULL AS STRING) AS FIRST_NAME, CAST(NULL AS STRING) AS LAST_NAME,
        CAST(NULL AS STRING) AS EMAIL, CAST(NULL AS STRING) AS COMPANY_NAME,
        CAST(NULL AS STRING) AS JOB_TITLE, CAST(NULL AS STRING) AS JOB_FUNCTION,
        CAST(NULL AS STRING) AS JOB_LEVEL, CAST(NULL AS STRING) AS OPT_IN,
        CAST(NULL AS STRING) AS ASSET_1, CAST(NULL AS STRING) AS ASSET_2,
        CAST(NULL AS STRING) AS CAMPAIGN, CAST(NULL AS STRING) AS PHONE,
        CAST(NULL AS STRING) AS INDUSTRY_NAME, CAST(NULL AS INT64) AS WEBSITE,
        CAST(NULL AS STRING) AS STATE, r.MARKET_REGION AS REGION, CAST(NULL AS STRING) AS COUNTRY_NAME,
        CAST(NULL AS FLOAT64) AS ANNUAL_REVENUE_, CAST(NULL AS STRING) AS CAMPAIGN_ID,
        CAST(NULL AS FLOAT64) AS LEADS, CONCAT('DUMMY_', GENERATE_UUID()) AS LEAD_ID_SF,
        'Accepted' AS STATUS, CAST(NULL AS STRING) AS LEAD_STATUS,
        CAST(NULL AS STRING) AS PUBLISHER, CAST(NULL AS STRING) AS OFFER_TYPE, CAST(NULL AS STRING) AS PUBLISHER_OFFER,
        CAST(NULL AS STRING) AS L2,
        r.MARKET_REGION AS MARKET_REGION,
        0 AS RIG,
        r.TIER AS TIER,
        CAST(NULL AS STRING) AS SERVICE,
        0 AS LEAD_VALUE,
        0 AS ANZ, 0 AS ASEAN, 0 AS SAARC, 0 AS GCR, 0 AS KR, 0 AS JP,
        CAST(r.REMAINING_TARGET AS FLOAT64) AS ALLOCATED_TARGET
    FROM target_remaining r
    WHERE r.REMAINING_TARGET > 0
),

-- B6. Union real leads + dummies (LEADS/ALLOCATED_TARGET cast in leads_allocated to match dummy types)
combined AS (
    SELECT
        DT_CREATED, DT_UPDATED, DT_FILENAME, DAY, FIRST_NAME, LAST_NAME, EMAIL,
        COMPANY_NAME, JOB_TITLE, JOB_FUNCTION, JOB_LEVEL, OPT_IN, ASSET_1, ASSET_2,
        CAMPAIGN, PHONE, INDUSTRY_NAME, WEBSITE, STATE, REGION, COUNTRY_NAME,
        ANNUAL_REVENUE_, CAMPAIGN_ID, CAST(LEADS AS FLOAT64) AS LEADS, LEAD_ID_SF,
        CAST(STATUS AS STRING) AS STATUS, LEAD_STATUS, PUBLISHER, OFFER_TYPE, PUBLISHER_OFFER, L2, MARKET_REGION,
        RIG, TIER, SERVICE, LEAD_VALUE, ANZ, ASEAN, SAARC, GCR, KR, JP,
        CAST(ALLOCATED_TARGET AS FLOAT64) AS ALLOCATED_TARGET
    FROM leads_allocated
    UNION ALL
    SELECT * FROM dummy_rows
)

SELECT
    *,
    SUM(LEAD_VALUE)       OVER (PARTITION BY MARKET_REGION, TIER ORDER BY DATE_TRUNC(DAY, WEEK(MONDAY))) AS CUMULATIVE_ACTUAL,
    SUM(ALLOCATED_TARGET) OVER (PARTITION BY MARKET_REGION, TIER ORDER BY DATE_TRUNC(DAY, WEEK(MONDAY))) AS CUMULATIVE_TARGET
FROM combined;
