-- salesforce_leads_live: Content-Syndication leads with the canonical 12-campaign
-- filter + region/publisher/offer derivation. BigQuery port of
-- CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE, now reading the mirror
-- raw_snowflake.salesforce_cs_apac_all instead of APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL".
-- The campaign-ID filter + the KR/RIG segment ID sets + the RIG assets are now SEED-DRIVEN:
-- they live in clients/client_cloudflare/definitions.json (the single source of truth shared with
-- the status verifier) and are materialised into client_cloudflare.seed_* tables by definitions_seed.py.
-- Editing them is a one-place change (definitions.json) that reloads the seed tables — this view's
-- structure never changes. The 12 IDs: 6 El* + 2 N* (2026-06-10) + 4 P* Modernize (2026-06-17).
--
-- KR + RIG are CLIENT-DEFINED segments (2026-06-19), NOT the old purely-geographic buckets:
--   * KR  = Korea ('Korea, Republic of') AND the 6 ORIGINAL El* campaigns only (Roverpath +
--           Final Funnel). Korea leads from the Connectivity-Cloud / Modernize campaigns are
--           deliberately EXCLUDED (they fall to OTHER).  ~164 leads.
--   * RIG = the gaming-vertical "Modernize Applications" asset (ASSET_2 = "Asset Title 2" in
--           Salesforce; values A-MAM-2 / A-MAM-3 — only A-MAM-3 has data today) on the 3 Final
--           Funnel campaigns, for NON-Korea leads. RIG is ASSET-based, not geographic, so it
--           spans every country — hence it is evaluated BEFORE the five geographic buckets and
--           pulls those leads out of ANZ/ASEAN/SAARC/GCR/JP (the overlap is intentional).  ~180 leads.
-- This is the SAME logic the status dashboard reproduces straight from Snowflake (Korea / RIG
-- checks in status_dashboard/job/main.py). The other five regions stay purely geographic.
-- The redefinition applies to CS LEADS ONLY — paid-media (TTD) KR/RIG market buckets are unaffected.
CREATE OR REPLACE VIEW `client_cloudflare.salesforce_leads_live` AS
SELECT
    DT_CREATED, DT_UPDATED, DT_FILENAME, DAY, FIRST_NAME, LAST_NAME, EMAIL,
    COMPANY_NAME, JOB_TITLE, JOB_FUNCTION, JOB_LEVEL, OPT_IN, ASSET_1, ASSET_2,
    CAMPAIGN, PHONE, INDUSTRY_NAME, WEBSITE, STATE, REGION, COUNTRY_NAME,
    ANNUAL_REVENUE_, CAMPAIGN_ID, LEADS, LEAD_ID_SF, STATUS, LEAD_STATUS,
    CASE
        -- RIG (client def): Modernize-Applications asset, 3 Final Funnel campaigns, non-Korea.
        -- FIRST so it claims these leads across all geographies (intentional overlap with ANZ/.../JP).
        WHEN COUNTRY_NAME <> 'Korea, Republic of'
             AND ASSET_2 IN (SELECT asset_2 FROM `bidbrain-analytics.client_cloudflare.seed_rig_assets`)
             AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_rig_campaign_ids`) THEN 'RIG'
        -- KR (client def): Korea + the 6 original El* campaigns ONLY (not Connectivity Cloud / Modernize).
        WHEN COUNTRY_NAME = 'Korea, Republic of'
             AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`) THEN 'KR'
        -- The other five regions remain purely geographic.
        WHEN COUNTRY_NAME IN ('Australia', 'New Zealand') THEN 'ANZ'
        WHEN COUNTRY_NAME IN ('Singapore', 'Malaysia', 'Indonesia', 'Thailand', 'Philippines', 'Viet Nam', 'Vietnam') THEN 'ASEAN'
        WHEN COUNTRY_NAME = 'India' THEN 'SAARC'
        WHEN COUNTRY_NAME IN ('China', 'Taiwan', 'Hong Kong') THEN 'GCR'
        WHEN COUNTRY_NAME = 'Japan' THEN 'JP'
        -- Residual: Korea leads outside the 6 El* campaigns + any non-RIG lead in an unlisted /
        -- mis-cased country. NOT one of the dashboard's 7 market chips, so it is excluded from the dash.
        ELSE 'OTHER'
    END AS REGION_GRP,
    CASE
        WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN', '701RG00001ElTu3YAF', '701RG00001ElVXdYAN') THEN 'Roverpath'
        WHEN CAMPAIGN_ID IN ('701RG00001ElUoXYAV', '701RG00001ElUa0YAF', '701RG00001ElNYkYAN') THEN 'Final Funnel'
        ELSE 'Unknown'
    END AS PUBLISHER,
    CASE
        WHEN CAMPAIGN_ID IN ('701RG00001ElJZzYAN', '701RG00001ElUoXYAV') THEN 'Precision MQL'
        WHEN CAMPAIGN_ID IN ('701RG00001ElTu3YAF', '701RG00001ElUa0YAF') THEN 'Pulse Survey'
        WHEN CAMPAIGN_ID IN ('701RG00001ElVXdYAN', '701RG00001ElNYkYAN') THEN 'Qualification Questions'
        ELSE 'Unknown'
    END AS OFFER_TYPE,
    CASE
        WHEN CAMPAIGN_ID = '701RG00001ElJZzYAN' THEN 'Roverpath - Precision MQL'
        WHEN CAMPAIGN_ID = '701RG00001ElTu3YAF' THEN 'Roverpath - Pulse Survey'
        WHEN CAMPAIGN_ID = '701RG00001ElVXdYAN' THEN 'Roverpath - Qualification Questions'
        WHEN CAMPAIGN_ID = '701RG00001ElUoXYAV' THEN 'Final Funnel - Precision MQL'
        WHEN CAMPAIGN_ID = '701RG00001ElUa0YAF' THEN 'Final Funnel - Pulse Survey'
        WHEN CAMPAIGN_ID = '701RG00001ElNYkYAN' THEN 'Final Funnel - Qualification Questions'
        ELSE 'Unknown'
    END AS PUBLISHER_OFFER
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
-- The 12-campaign filter now comes from the seed table (loaded from definitions.json).
WHERE CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_cs_campaign_ids`);
