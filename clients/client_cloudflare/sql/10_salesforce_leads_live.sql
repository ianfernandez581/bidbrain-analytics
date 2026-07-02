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
-- REGION_GRP = the 11 media-plan markets + a residual OTHER (2026-06-25 grain; KR reverted 2026-07-02).
-- The country match is case-normalised so mis-cased countries can't fall through.
--   * RIG = the gaming-vertical "Modernize Applications" asset (ASSET_2 = "Asset Title 2" in
--           Salesforce; values A-MAM-2 / A-MAM-3 — only A-MAM-3 has data today) on the 3 Final
--           Funnel campaigns, for NON-Korea leads. ASSET-based, not geographic, so evaluated
--           BEFORE geography and pulls those leads out of every market (the overlap is intentional).
--   * KR  = Korea ('Korea, Republic of') leads in the 6 ORIGINAL El* CS campaigns ONLY (~164).
--           2026-07-02: reverted the 2026-06-25 "all Korea in the 12 campaigns" rule at the client's
--           request. Korea leads from the other 6 campaigns (Connectivity Cloud / Modernize Security /
--           Modernize Applications) fall through to OTHER, which is NOT a market chip -> excluded from
--           the dash (its totals sum over the 11 chips), matching pre-2026-06-25 behaviour.
--   * The geographic markets are SPLIT to the media plan's grain: AU, NZ, SIM (SG/MY/ID),
--           ROA (TH/VN/PH), SAARC (IN), GCR-CN, GCR-TW, GCR-HK, JP.
-- The status dashboard reproduces KR / RIG straight from Snowflake (status_dashboard/job/main.py).
-- This applies to CS LEADS ONLY — paid-media (TTD) KR/RIG market buckets are unaffected.
CREATE OR REPLACE VIEW `client_cloudflare.salesforce_leads_live` AS
SELECT
    DT_CREATED, DT_UPDATED, DT_FILENAME, DAY, FIRST_NAME, LAST_NAME, EMAIL,
    COMPANY_NAME, JOB_TITLE, JOB_FUNCTION, JOB_LEVEL, OPT_IN, ASSET_1, ASSET_2,
    CAMPAIGN, PHONE, INDUSTRY_NAME, WEBSITE, STATE, REGION, COUNTRY_NAME,
    ANNUAL_REVENUE_, CAMPAIGN_ID, LEADS, LEAD_ID_SF, STATUS, LEAD_STATUS,
    CASE
        -- RIG (client def): gaming-vertical "Modernize Applications" asset on the 3 Final Funnel
        -- campaigns, NON-Korea. Evaluated FIRST so it claims these leads across all geographies.
        WHEN UPPER(TRIM(COUNTRY_NAME)) <> 'KOREA, REPUBLIC OF'
             AND ASSET_2 IN (SELECT asset_2 FROM `bidbrain-analytics.client_cloudflare.seed_rig_assets`)
             AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_rig_campaign_ids`) THEN 'RIG'
        -- KR = Korea leads in the 6 ORIGINAL El* CS campaigns ONLY (3 Roverpath + 3 Final Funnel
        -- Lead-Gen). 2026-07-02: reverted the 2026-06-25 "all Korea in the 12 campaigns" rule at the
        -- client's request -- Korea now counts ONLY these 6. Korea leads from the other 6 campaigns
        -- (Connectivity Cloud / Modernize Security / Modernize Applications) fall through to OTHER
        -- (not a market chip, so excluded from the dash). Seed-driven: seed_kr_campaign_ids.
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'KOREA, REPUBLIC OF'
             AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`) THEN 'KR'
        -- Geographic markets, case-normalised (UPPER(TRIM)) so mis-cased countries ('japan',
        -- 'Hong kong', 'india') route correctly instead of falling to OTHER. The old 7-region map
        -- is SPLIT to the media plan's granular markets (2026-06-25):
        --   ANZ -> AU / NZ ;  ASEAN -> SIM / ROA ;  GCR -> GCR-CN / GCR-TW / GCR-HK.
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'AUSTRALIA'                                       THEN 'AU'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'NEW ZEALAND'                                     THEN 'NZ'
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('SINGAPORE', 'MALAYSIA', 'INDONESIA')           THEN 'SIM'
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('THAILAND', 'VIET NAM', 'VIETNAM', 'PHILIPPINES') THEN 'ROA'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'INDIA'                                           THEN 'SAARC'
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('CHINA', 'MAINLAND CHINA')                      THEN 'GCR-CN'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'TAIWAN'                                          THEN 'GCR-TW'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'HONG KONG'                                       THEN 'GCR-HK'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'JAPAN'                                           THEN 'JP'
        -- Residual: holds Korea leads outside the 6 KR campaigns (2026-07-02, ~36) plus any
        -- brand-new/unmapped country. OTHER is NOT a market chip, so these are excluded from the
        -- dash (its totals sum over the 11 chips); the status dashboard reports the OTHER count.
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
