-- ============================================================================
-- MANUAL SNOWFLAKE DDL -- run by a role with OWNERSHIP on
--   CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE
-- (the client/Transmission owning role, or ACCOUNTADMIN).
--
-- NOT applied by create_views.py (that targets BigQuery sql/*.sql). This file
-- lives at the client root on purpose so the BigQuery pipeline ignores it.
--
-- WHY: the Cloudflare CS dashboard understated leads because this feeder view's
-- CAMPAIGN_ID filter lagged the live CS APAC campaign set. History:
--   2026-06-10  6 -> 8 IDs  (added 701RG00001NJd6NYAT, 701RG00001NIYRKYA5).
--   2026-06-17  8 -> 12 IDs (added the four Modernize Security / Modernize
--               Applications campaigns now running: 701RG00001PXNyDYAX,
--               701RG00001PWX5gYAH, 701RG00001PXLpxYAH, 701RG00001PXHnzYAH
--               ~= 267 leads). The full canonical set is the 12 IDs below.
-- The pacing view V_PACING_FINAL_MODEL is pass-through on campaigns, so this is
-- the only edit needed. Everything else is byte-for-byte the current definition.
--
-- NOTE (2026-06-19): the REGION_GRP logic below is the OLD purely-geographic mapping and is kept
-- for Cloudflare's own legacy R2 export. OUR BigQuery pipeline (sql/10_salesforce_leads_live.sql)
-- now DIVERGES: KR + RIG are client-defined CS segments (KR = Korea on the 6 El* campaigns; RIG =
-- the A-MAM Modernize-Applications asset on the 3 Final Funnel campaigns, non-Korea). Do NOT copy
-- the geographic RIG below into the BQ view — see clients/client_cloudflare/sql/README.md.
--
-- UPDATE (2026-07-02): the KR arm below was campaign-scoped to the 6 original El* campaigns at the
-- client's request (Korea counts only these 6, matching the BQ pipeline). This is the ONLY change to
-- the legacy mapping; RIG stays the geographic Rest-of-APAC catch-all. NOT YET APPLIED to Snowflake:
-- our pipeline roles are read-only (see below) — an owner/ACCOUNTADMIN must run this CREATE OR REPLACE
-- (keep the `copy grants`). Until then Transmission's own view still buckets all Korea into KR.
--
-- Our pipeline roles (APAC_IN_ROLE via the MCP connector; BQ_SYNC_ROLE via the
-- export job key-pair) are read-only and CANNOT apply this -- 003001/42501.
--
-- CRITICAL -- ALWAYS keep the `copy grants` below. Applying this WITHOUT it
-- (e.g. a hand-edited paste) drops every SELECT grant on the view and the
-- consumer roles lose access ("Schema ... not authorized"). If that happens,
-- recover under ACCOUNTADMIN with:
--   GRANT SELECT ON VIEW CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE
--     TO ROLE BQ_SYNC_ROLE;     -- the export job (reads V_PACING_FINAL_MODEL)
--   GRANT SELECT ON VIEW CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE
--     TO ROLE APAC_IN_ROLE;     -- the MCP connector (verification)
-- ============================================================================
create or replace view CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE(
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
	REGION_GRP,
	PUBLISHER,
	OFFER_TYPE,
	PUBLISHER_OFFER
) copy grants as           -- COPY GRANTS: preserve existing SELECT grants across the
                           -- replace. WITHOUT it, CREATE OR REPLACE wipes every grant on
                           -- the view AND resets its owner to the running role -> the
                           -- export job's BQ_SYNC_ROLE + the MCP APAC_IN_ROLE lose SELECT
                           -- (and ownership-chaining from V_PACING_FINAL_MODEL breaks).
SELECT
    /* STABILITY FIX:
       We explicitly list these 27 columns instead of using SELECT *.
       This prevents the "28 vs 29 column" metadata mismatch error.
       By naming them, the view remains stable even if the raw source table
       ("Salesforce_CS_APAC_ALL") is updated with new fields by Adverity.
    */
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

    /* REGION GROUPING LOGIC:
       This replaces the Looker Studio calculated fields to improve dashboard performance.
       - Normalizes naming variations (e.g., 'Viet Nam' vs 'Vietnam').
       - Groups China, Taiwan, and Hong Kong into 'GCR'.
       - Groups all non-specified markets into 'RIG' (Rest of APAC) as requested,
         effectively eliminating the "Others" bucket in the dashboard.
    */
    CASE
        WHEN COUNTRY_NAME IN ('Australia', 'New Zealand') THEN 'ANZ'
        WHEN COUNTRY_NAME IN ('Singapore', 'Malaysia', 'Indonesia', 'Thailand', 'Philippines', 'Viet Nam', 'Vietnam') THEN 'ASEAN'
        WHEN COUNTRY_NAME = 'India' THEN 'SAARC'
        WHEN COUNTRY_NAME IN ('China', 'Taiwan', 'Hong Kong') THEN 'GCR'
        -- KR restricted to the 6 ORIGINAL El* CS campaigns (2026-07-02, client request) so Korea
        -- counts only these 6 here too. Korea leads from the other 6 campaigns fall to the ELSE 'RIG'
        -- (this view's Rest-of-APAC catch-all) rather than a separate OTHER.
        WHEN COUNTRY_NAME IN ('Korea, Republic of', 'Korea', 'South Korea')
             AND CAMPAIGN_ID IN (
                 '701RG00001ElJZzYAN', -- Roverpath - Precision MQL
                 '701RG00001ElTu3YAF', -- Roverpath - Pulse Survey
                 '701RG00001ElVXdYAN', -- Roverpath - Qualification Questions
                 '701RG00001ElUoXYAV', -- Final Funnel - Precision MQL
                 '701RG00001ElUa0YAF', -- Final Funnel - Pulse Survey
                 '701RG00001ElNYkYAN'  -- Final Funnel - Qualification Questions
             ) THEN 'KR'
        WHEN COUNTRY_NAME = 'Japan' THEN 'JP'
        ELSE 'RIG'
    END AS REGION_GRP,

    /* 1. PUBLISHER LOGIC:
       High-level grouping for Vendor performance comparisons.
       NOTE: the six newly-added campaign IDs (NJd6N/NIYRK 2026-06-10; the four
       Modernize* IDs 2026-06-17) are not mapped here and resolve to 'Unknown'
       until the client supplies their publisher/offer.
    */
    CASE
        WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN', '701RG00001ElTu3YAF', '701RG00001ElVXdYAN') THEN 'Roverpath'
        WHEN CAMPAIGN_ID IN ('701RG00001ElUoXYAV', '701RG00001ElUa0YAF', '701RG00001ElNYkYAN') THEN 'Final Funnel'
        ELSE 'Unknown'
    END AS PUBLISHER,

    /* 2. OFFER TYPE LOGIC:
       Granular grouping for specific campaign details.
    */
    CASE
        WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN', '701RG00001ElUoXYAV') THEN 'Precision MQL'
        WHEN CAMPAIGN_ID IN ('701RG00001ElTu3YAF', '701RG00001ElUa0YAF') THEN 'Pulse Survey'
        WHEN CAMPAIGN_ID IN ('701RG00001ElVXdYAN', '701RG00001ElNYkYAN') THEN 'Qualification Questions'
        ELSE 'Unknown'
    END AS OFFER_TYPE,

    /* 3. COMBINED PUBLISHER & OFFER LOGIC:
       Maps each Campaign ID directly to the exact combined string.
    */
    CASE
        WHEN CAMPAIGN_ID = '701RG00001ElJZzYAN' THEN 'Roverpath - Precision MQL'
        WHEN CAMPAIGN_ID = '701RG00001ElTu3YAF' THEN 'Roverpath - Pulse Survey'
        WHEN CAMPAIGN_ID = '701RG00001ElVXdYAN' THEN 'Roverpath - Qualification Questions'
        WHEN CAMPAIGN_ID = '701RG00001ElUoXYAV' THEN 'Final Funnel - Precision MQL'
        WHEN CAMPAIGN_ID = '701RG00001ElUa0YAF' THEN 'Final Funnel - Pulse Survey'
        WHEN CAMPAIGN_ID = '701RG00001ElNYkYAN' THEN 'Final Funnel - Qualification Questions'
        ELSE 'Unknown'
    END AS PUBLISHER_OFFER

FROM APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL"

/* CAMPAIGN ID FILTERING:
   We filter for the canonical 12 IDs of the CS APAC campaign set.
   (2026-06-10) Added NJd6N/NIYRK; (2026-06-17) added the four Modernize
   Security / Modernize Applications IDs -- previously excluded, which
   understated Accepted/Rejected/New lead counts on the dash.
*/
WHERE CAMPAIGN_ID IN (
    '701RG00001ElJZzYAN', -- Roverpath - Precision MQL
    '701RG00001ElTu3YAF', -- Roverpath - Pulse Survey
    '701RG00001ElVXdYAN', -- Roverpath - Qualification Questions
    '701RG00001ElUoXYAV', -- Final Funnel - Precision MQL
    '701RG00001ElUa0YAF', -- Final Funnel - Pulse Survey
    '701RG00001ElNYkYAN', -- Final Funnel - Qualification Questions
    '701RG00001NJd6NYAT', -- (added 2026-06-10) Roverpath - Connectivity Cloud (ANZ)
    '701RG00001NIYRKYA5', -- (added 2026-06-10) Final Funnel CF1 - Connectivity Cloud (ANZ)
    '701RG00001PXNyDYAX', -- (added 2026-06-17) Final Funnel ABM - Modernize Security (ANZ)
    '701RG00001PWX5gYAH', -- (added 2026-06-17) Final Funnel ABM - Modernize Security (ANZ)
    '701RG00001PXLpxYAH', -- (added 2026-06-17) Roverpath - Modernize Applications (ANZ)
    '701RG00001PXHnzYAH'  -- (added 2026-06-17) Roverpath - Modernize Applications (ANZ)
);

-- ---------------------------------------------------------------------------
-- VERIFY (run after the CREATE OR REPLACE). View must agree with raw source:
--   SELECT COUNT(*) total,
--          COUNT_IF(LEAD_STATUS IN ('Accepted','Replied','Unresponsive')) accepted,
--          COUNT_IF(LEAD_STATUS='Rejected') rejected,
--          COUNT_IF(LEAD_STATUS='New') new_
--   FROM CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL
--   WHERE LEAD_ID_SF IS NULL OR LEAD_ID_SF NOT LIKE 'DUMMY%';
-- Expected ~ total 3911 | accepted 3328 | rejected 416 | new 167  (12 IDs, as of 2026-06-17)
-- ---------------------------------------------------------------------------
