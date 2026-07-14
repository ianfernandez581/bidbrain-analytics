-- 29_crm_lifecycle_owner.sql — Q4: which lifecycle stage are my leads in and who owns them?
-- Grain: (created_month, owner_name, lifecycle_stage) with contact counts + paying/signup
-- context. created_month = the month the contact was created in HubSpot, so the Signups &
-- CRM tab's date-range picker can scope owner × stage to a created-date cohort (the frontend
-- SUMs the in-window months per owner × stage). Unassigned contacts roll up under
-- 'Unassigned'. Frontend pivots owner × stage.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_lifecycle_owner` AS
SELECT
  FORMAT_TIMESTAMP('%Y-%m', c.hs_created_at)               AS created_month,
  COALESCE(o.owner_name,
           IF(c.owner_id IS NULL OR c.owner_id = '', 'Unassigned', 'Inactive owner')) AS owner_name,
  COALESCE(c.lifecycle_stage, 'Unknown')                   AS lifecycle_stage,
  COUNT(*)                                                 AS contacts,
  COUNTIF(c.is_app_signup)                                 AS signups,
  COUNTIF(c.is_paying)                                     AS paying,
  COUNTIF(c.has_deal)                                      AS with_deal
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts` c
LEFT JOIN `bidbrain-analytics.client_resetdata.hubspot_owners` o
  ON c.owner_id = o.owner_id
GROUP BY created_month, owner_name, lifecycle_stage
ORDER BY contacts DESC;
