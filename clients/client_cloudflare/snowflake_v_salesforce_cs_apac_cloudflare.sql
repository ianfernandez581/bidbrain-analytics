-- REFERENCE DDL - Snowflake-side, NOT part of our pipeline (nothing in this repo reads or
-- mirrors this view; it is Calvin's EDA/scoping view in APAC_ALL_PLATFORM.PUBLIC).
--
-- WHY THIS FILE EXISTS (2026-08-31): the deployed view declared 28 columns but selected
-- `t.* + REGION_GRP`. The base table "Salesforce_CS_APAC_ALL" gained LEAD_STATUS_SF, so the
-- query started returning 29 columns against the declared 28 and EVERY select against the
-- view errored (the Snowflake flavour of md/AGENTS.md's "a SELECT * mirror means upstream can
-- change your schema without telling you"). The fix names every column explicitly, so a
-- future base-table addition cannot break the view again - it just doesn't flow until added.
--
-- APPLY AS: a role with OWNERSHIP on the view (it is owned by ACCOUNTADMIN; APAC_IN_ROLE is
-- read-only on the schema, and the MCP connection cannot USE ROLE). Paste-and-run in the
-- Snowflake UI under ACCOUNTADMIN. Verified against the live base schema 2026-08-31.
CREATE OR REPLACE VIEW APAC_ALL_PLATFORM.PUBLIC.V_SALESFORCE_CS_APAC_CLOUDFLARE AS
SELECT
  t.DT_CREATED, t.DT_UPDATED, t.DT_FILENAME, t.DAY,
  t.FIRST_NAME, t.LAST_NAME, t.EMAIL, t.COMPANY_NAME,
  t.JOB_TITLE, t.JOB_FUNCTION, t.JOB_LEVEL, t.OPT_IN,
  t.ASSET_1, t.ASSET_2, t.CAMPAIGN, t.PHONE,
  t.INDUSTRY_NAME, t.WEBSITE, t.STATE, t.REGION,
  t.COUNTRY_NAME, t.ANNUAL_REVENUE_, t.CAMPAIGN_ID, t.LEADS,
  t.LEAD_ID_SF, t.STATUS, t.LEAD_STATUS, t.LEAD_STATUS_SF,
  CASE
    WHEN COUNTRY_NAME IN ('Australia', 'New Zealand') THEN 'ANZ'
    WHEN COUNTRY_NAME IN ('Singapore', 'Malaysia', 'Indonesia',
                          'Thailand', 'Philippines', 'Viet Nam', 'Vietnam') THEN 'ASEAN'
    WHEN COUNTRY_NAME = 'India' THEN 'SAARC'
    WHEN COUNTRY_NAME IN ('China', 'Taiwan', 'Hong Kong') THEN 'GCR'
    WHEN COUNTRY_NAME IN ('Korea, Republic of', 'Korea', 'South Korea') THEN 'KR'
    WHEN COUNTRY_NAME = 'Japan' THEN 'JP'
    ELSE 'RIG'
  END AS REGION_GRP
FROM APAC_ALL_PLATFORM.PUBLIC."Salesforce_CS_APAC_ALL" t
WHERE CAMPAIGN_ID IN (
  '701RG00001ElJZzYAN',  -- Roverpath_Precision MQL_Lead Gen
  '701RG00001ElTu3YAF',  -- Roverpath_Conversion_Pulse survey_Lead Gen
  '701RG00001ElVXdYAN',  -- Roverpath_Conversion_Qualification Questions_Lead Gen
  '701RG00001ElUoXYAV',  -- Final Funnel_Precision MQL_Lead Gen
  '701RG00001ElUa0YAF',  -- Final Funnel_Conversion_Pulse survey_Lead Gen
  '701RG00001ElNYkYAN'   -- Final Funnel_Conversion_Qualification Questions_Lead Gen
);
