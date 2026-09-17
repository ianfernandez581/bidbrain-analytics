-- 13_stg_salesforce: Geocon CRM enquiries (Salesforce leads via Windsor), daily x development.
--
-- The raw layer is raw_windsor.geocon_salesforce_leads, written by the scheduled
-- windsor-salesforce-ingest job (ingest/windsor_data_pull/salesforce/). It carries NO PII by
-- design -- lead id, created date, project, source, status and nothing else.
--
-- WHY THIS EXISTS. The dashboard's `leads` column is PLATFORM-REPORTED (Meta's own lead count,
-- attribution-modelled). Geocon count enquiries in Salesforce. Those are different numbers for
-- the same month and always will be: over 20 Aug - 15 Sep 2026 the platforms claimed 156 while
-- Salesforce held 115 and Geocon's own website export recorded 124 distinct people. This view is
-- the CRM number, kept as its own series so the two can be shown side by side and neither has to
-- be bent to match the other.
--
-- ============================================================================================
-- *** THE DEVELOPMENT SPLIT IS A STATED RULE, NOT A FACT THE CRM CARRIES. READ THIS. ***
-- ============================================================================================
-- Salesforce has exactly ONE 'Gateway' project record (Project__c a0pRF000004XU6fYAG), used from
-- 2024-01-07 to today, and it covers BOTH Gateway Braddon AND Northbourne Gateway. Verified
-- 2026-09-17 against every field that could separate them:
--
--     field                      Braddon era (May-20 Jul)   Northbourne era (20 Aug+)
--     Development_Name__c        'Gateway' (128/128)        'Gateway' (133/137)
--     Project_of_Interest__c     a0pRF000004XU6fYAG         a0pRF000004XU6fYAG  (same id)
--     Website / UTMSource__c     blank                      blank
--     Enquiry_Source__c          blank                      blank
--
-- Only the DATE differs. So the split below is an inference from the campaign calendar -- Gateway
-- Braddon's flight ended 2026-07-20, Northbourne Gateway launched 2026-08-20 -- and it is stated
-- here, once, as a named constant rather than buried in a CASE. It is NOT a clean CRM attribution
-- and the dashboard says so on screen.
--
-- WHAT IT GETS WRONG, AND IN WHICH DIRECTION: Gateway Braddon is a real building with a live
-- landing page (117 of its 128 flight-era leads came from 'Project Landing Page'), so any
-- enquiry it still attracts is counted as Northbourne's. The error therefore OVERSTATES
-- Northbourne. Do not present this figure as a per-development CRM truth.
--
-- THE DURABLE FIX is Geocon splitting the project record, or adding a development field to the
-- web forms. When that lands: drop SPLIT_DATE, resolve `property` off the real field, and delete
-- this comment block. Until then, changing the cutover is a one-line edit here.
--
-- OTHER DEVELOPMENTS ARE EXCLUDED ON PURPOSE. The org runs The Grande (3,937 leads), WOVA (1,755),
-- Vue Greenway and others; none is on this dashboard, so none is in scope. The loader logs the
-- full project breakdown every run, so a NEW Geocon development announces itself in the job log
-- instead of silently missing. A project that should appear here needs a row added to the
-- scope CTE below -- never a catch-all ELSE, which would file a stranger under a live client.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_salesforce` AS
WITH scope AS (
  -- The ONLY project on this dashboard. Matched on the project NAME, with the record id carried
  -- so a rename is visible rather than silently emptying the view (AGENTS.md: names are not
  -- stable keys -- the id is the stable one, the name is the label).
  SELECT
    created_date                                   AS date,
    lead_id,
    project_id,
    project_name,
    NULLIF(TRIM(lead_source), '')                  AS lead_source,
    NULLIF(TRIM(lead_status), '')                  AS lead_status
  FROM `bidbrain-analytics.raw_windsor.geocon_salesforce_leads`
  WHERE project_name = 'Gateway'
    AND created_date IS NOT NULL
)
SELECT
  date,
  -- The stated split. 2026-08-20 is Northbourne Gateway's launch and the first day of its
  -- reporting window; Gateway Braddon's flight had ended a month earlier (2026-07-20).
  CASE WHEN date >= DATE '2026-08-20' THEN 'Northbourne Gateway'
       ELSE 'Gateway Braddon' END                  AS property,
  -- Kept as a dimension, never as an attribution. Salesforce LeadSource names a channel FAMILY
  -- ('Project Landing Page', 'Facebook'), never a campaign or an ad, so it can group enquiries
  -- but can never cost one against the media that produced it.
  COALESCE(lead_source, '(not set)')               AS lead_source,
  COALESCE(lead_status, '(not set)')               AS lead_status,
  COUNT(DISTINCT lead_id)                          AS leads
FROM scope
GROUP BY date, property, lead_source, lead_status
