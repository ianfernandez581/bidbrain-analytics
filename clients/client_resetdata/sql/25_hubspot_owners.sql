-- 25_hubspot_owners.sql — owner_id -> display name (resolves the numeric HubSpot owner
-- id on contacts/deals to a person for the "who owns this lead" / BDM-queue views).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.hubspot_owners` AS
SELECT
  owner_owner_id AS owner_id,
  COALESCE(
    NULLIF(TRIM(CONCAT(COALESCE(owner_first_name, ''), ' ', COALESCE(owner_last_name, ''))), ''),
    owner_email,
    CONCAT('Owner ', owner_owner_id)
  ) AS owner_name,
  owner_email,
  (LOWER(owner_archived) = 'true') AS archived
FROM `bidbrain-analytics.raw_windsor.hubspot_owners`
WHERE owner_owner_id IS NOT NULL;
