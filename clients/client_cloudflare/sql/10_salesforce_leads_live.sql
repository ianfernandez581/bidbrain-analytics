-- salesforce_leads_live: Content-Syndication leads with the canonical 13-campaign
-- filter + region/publisher/offer derivation. BigQuery port of
-- CLOUDFLARE_SANDBOX.CS_REPORTING.V_SALESFORCE_LEADS_LIVE, now reading the mirror
-- raw_snowflake.salesforce_cs_apac_all instead of APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL".
-- The campaign-ID filter + the KR/RIG segment ID sets + the RIG assets are now SEED-DRIVEN:
-- they live in clients/client_cloudflare/definitions.json (the single source of truth shared with
-- the status verifier) and are materialised into client_cloudflare.seed_* tables by definitions_seed.py.
-- Editing them is a one-place change (definitions.json) that reloads the seed tables — this view's
-- structure never changes. The 13 IDs: 6 El* + 2 N* (2026-06-10) + 4 P* Modernize (2026-06-17)
-- + 1 W* (701RG00001W1FQRYA3, 2026-07-10 — Q3 ANZ VSRM Lead Magnet, Tier 3; PUBLISHER/OFFER 'Unknown').
--
-- REGION_GRP = the COARSE 7 markets + a residual OTHER (2026-07-07 grain; rolled back UP from the
-- 2026-06-25 11-chip split at the client's request -- see the Jade call). The country match is
-- case-normalised so mis-cased countries can't fall through.
--   * RIG = the gaming-vertical "Modernize Applications" asset (ASSET_2 = "Asset Title 2" in
--           Salesforce; values A-MAM-2 / A-MAM-3 — only A-MAM-3 has data today) on the 3 Final
--           Funnel campaigns, for NON-Korea leads. ASSET-based, not geographic, so evaluated
--           BEFORE geography and pulls those leads out of every market (the overlap is intentional).
--   * KR  = Korea ('Korea, Republic of') leads in the 6 ORIGINAL El* CS campaigns ONLY. Dash shows
--           ~144 ACCEPTED; the client reports 164 DELIVERED (all statuses) -- the ~20 gap is
--           delivered-vs-accepted, not a match bug (see the reconciliation note by the KR arm below).
--           Korea leads from the other 6 campaigns fall through to OTHER (NOT a chip -> off the dash).
--   * The geographic markets are the COARSE 7: ANZ (AU+NZ), ASEAN (SG/MY/ID/TH/VN/PH),
--           SAARC (IN), GCR (CN/TW/HK), JP -- matching the paid-media L3 grain 1:1.
-- TEST leads on Transmission emails are excluded in the WHERE (see below).
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
        -- (Connectivity Cloud / Modernize Security / Modernize Applications) fall through to OTHER.
        -- Seed-driven: seed_kr_campaign_ids.
        -- Reconciliation note (2026-07-07, Jade call): the dash KR bucket shows ~144 ACCEPTED Korea
        -- leads; Nabeel reports 164 DELIVERED (101 Final Funnel + 63 Roverpath). The ~20 gap is almost
        -- certainly delivered(all statuses) vs accepted, NOT a country-name bug -- so the exact match is
        -- KEPT (a broadened LIKE '%KOREA%' would over-count and desync the status-dash check). Ian to
        -- confirm with the diagnostic query before any change (see clients/client_cloudflare/README.md).
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'KOREA, REPUBLIC OF'
             AND CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`) THEN 'KR'
        -- Geographic markets, case-normalised (UPPER(TRIM)) so mis-cased countries ('japan',
        -- 'Hong kong', 'india') route correctly instead of falling to OTHER. 2026-07-07: rolled back
        -- up to the COARSE 7 buckets (client request, per the Jade call) so CS markets match the
        -- paid-media L3 grain 1:1 -- ANZ = AU+NZ, ASEAN = SIM+RoA (SG/MY/ID/TH/VN/PH), GCR = CN/TW/HK.
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('AUSTRALIA', 'NEW ZEALAND')                     THEN 'ANZ'
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('SINGAPORE', 'MALAYSIA', 'INDONESIA',
                                           'THAILAND', 'VIET NAM', 'VIETNAM', 'PHILIPPINES') THEN 'ASEAN'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'INDIA'                                           THEN 'SAARC'
        WHEN UPPER(TRIM(COUNTRY_NAME)) IN ('CHINA', 'MAINLAND CHINA', 'TAIWAN', 'HONG KONG') THEN 'GCR'
        WHEN UPPER(TRIM(COUNTRY_NAME)) = 'JAPAN'                                           THEN 'JP'
        -- Residual: holds Korea leads outside the 6 KR campaigns plus any brand-new/unmapped country.
        -- OTHER is NOT a market chip, so these are excluded from the dash (its totals sum over the 7
        -- chips); the status dashboard reports the OTHER count.
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
-- The 13-campaign filter now comes from the seed table (loaded from definitions.json).
WHERE CAMPAIGN_ID IN (SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_cs_campaign_ids`)
  -- Exclude Transmission TEST leads (2026-07-07, per the Jade call): the vendors were sent
  -- >=2 test leads each, all on Transmission emails (Nabeel/Shalvi/Jade). They inflate the
  -- rejection rate and every count, so drop any lead whose email DOMAIN contains 'transmission'
  -- (covers transmission.com / transmissionagency.com / any Transmission variant). Real leads keep.
  AND LOWER(IFNULL(SPLIT(EMAIL, '@')[SAFE_OFFSET(1)], '')) NOT LIKE '%transmission%';
