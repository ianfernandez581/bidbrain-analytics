-- 29_crm_lifecycle_owner.sql — Q4: which lifecycle stage are my leads in and who owns them?
-- Grain: (owner_name, lifecycle_stage) with contact counts + paying/signup context.
-- Unassigned contacts roll up under 'Unassigned'. Frontend pivots owner × stage.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_lifecycle_owner` AS
SELECT
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
GROUP BY owner_name, lifecycle_stage
ORDER BY contacts DESC;
