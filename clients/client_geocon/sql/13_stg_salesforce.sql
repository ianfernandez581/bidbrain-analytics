-- 13_stg_salesforce: Geocon CRM leads (Salesforce via Windsor), daily x project.
--
-- The raw layer is raw_windsor.geocon_salesforce_leads, written by the scheduled
-- windsor-salesforce-ingest job (ingest/windsor_data_pull/salesforce/). It carries NO PII by
-- design -- lead id, created date, project, source, status and nothing else.
--
-- WHY THIS EXISTS. The dashboard's `leads` column is PLATFORM-REPORTED (Meta's own lead count,
-- attribution-modelled). Geocon count leads in Salesforce. Those are different numbers for the
-- same month and always will be: over 20 Aug - 15 Sep 2026 the platforms claimed 156 while
-- Salesforce held 115 for Gateway alone. This view is the CRM number, kept as its own series so
-- the two can sit side by side and neither has to be bent to match the other.
--
-- ============================================================================================
-- *** SCOPE IS EVERY GEOCON DEVELOPMENT (client decision, 2026-09-17). ***
-- ============================================================================================
-- This view was built scoped to the single 'Gateway' project and split between Gateway Braddon
-- and Northbourne Gateway on a date. The client widened it the same day: the lead figure is the
-- WHOLE BOOK - The Grande, WOVA, Vue Greenway, Lead Distribution, everything - not one
-- development.
--
-- TWO THINGS THAT CHANGE BECAUSE OF IT, and both are improvements:
--
--  1. THE DEVELOPMENT SPLIT IS GONE, and so is the inference behind it. Salesforce records
--     Gateway Braddon and Northbourne Gateway under ONE 'Gateway' project record
--     (a0pRF000004XU6fYAG) with nothing but the date to tell them apart, so the old `property`
--     column was a stated guess (leads from 2026-08-20 = Northbourne). A whole-book figure needs
--     no such guess, so the guess is deleted rather than carried.
--
--  2. THERE IS NO LONGER A COST PER LEAD, and there must not be. The spend on this dashboard is
--     ONE development's media; these leads are every development's. Dividing one by the other
--     credits Northbourne's budget with The Grande's enquiries - it read A$253.68 against a true
--     A$341.35 for the matched pair. The tile was removed in the same change. **Do not
--     reintroduce a cost-per-lead, a CPL column or a lead-based ROI anywhere that reads this
--     view** unless the numerator is narrowed back to the paying development.
--
-- `project` is carried so the mix stays auditable and a NEW Geocon development shows up by name
-- rather than silently joining a total. Nothing is excluded here: what the CRM holds is what the
-- dashboard reports, which is the whole point of the change.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.stg_salesforce` AS
SELECT
  created_date                                                      AS date,
  -- The Salesforce Project_of_Interest_Text__c label. '(not set)' is a REAL bucket (~1,051 leads
  -- over three years carry no project), never dropped - dropping it would stop the parts summing
  -- to the headline count.
  COALESCE(NULLIF(TRIM(project_name), ''), '(not set)')             AS project,
  -- Kept as dimensions, never as attribution. Salesforce LeadSource names a channel FAMILY
  -- ('Project Landing Page', 'Facebook'), never a campaign or an ad, so it can group leads but
  -- can never cost one against the media that produced it.
  COALESCE(NULLIF(TRIM(lead_source), ''), '(not set)')              AS lead_source,
  COALESCE(NULLIF(TRIM(lead_status), ''), '(not set)')              AS lead_status,
  COUNT(DISTINCT lead_id)                                           AS leads
FROM `bidbrain-analytics.raw_windsor.geocon_salesforce_leads`
WHERE created_date IS NOT NULL
GROUP BY date, project, lead_source, lead_status
