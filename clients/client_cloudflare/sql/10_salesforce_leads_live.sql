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
-- REGION_GRP = the 11 media-plan markets (2026-06-25 rework). There is NO 'OTHER' tab anymore:
-- every source country maps to a market, KR captures ALL Korea, and the country match is
-- case-normalised so mis-cased countries can't fall through.
--   * RIG = the gaming-vertical "Modernize Applications" asset (ASSET_2 = "Asset Title 2" in
--           Salesforce; values A-MAM-2 / A-MAM-3 — only A-MAM-3 has data today) on the 3 Final
--           Funnel campaigns, for NON-Korea leads. ASSET-based, not geographic, so evaluated
--           BEFORE geography and pulls those leads out of every market (the overlap is intentional).
--   * KR  = ALL Korea ('Korea, Republic of') leads in the 12 CS campaigns (~200). 2026-06-25:
--           the old "6 El* campaigns only" rule was dropped (it stranded ~36 Korea ABM leads in OTHER
--           and contradicted the media plan, which targets all of Korea at 202).
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
        -- KR = ALL Korea leads in the 12 CS campaigns. 2026-06-25: dropped the old "6 El* campaigns
        -- only" restriction -- the media plan targets all of Korea (~200 vs target 202), and the
        -- restriction was stranding ~36 Korea ABM (Modernize-Security) leads in OTHER.
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'KOREA, REPUBLIC OF' THEN 'KR'
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
        -- Defensive residual: with all source countries mapped above, this is currently EMPTY.
        -- Kept so a brand-new/unmapped country is caught (status dashboard reconciles totals).
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
