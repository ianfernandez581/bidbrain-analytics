-- 30_crm_lead_queue.sql — Q6: what leads does the BDM still need to sort through?
-- The working queue = non-customer leads that carry a sales lead-status (NEW / OPEN /
-- IN_PROGRESS / ATTEMPTED_TO_CONTACT / …). Grain: (created_month, lead_status, owner_name)
-- with an "unassigned" split. created_month = the month the contact was created in HubSpot,
-- so the Signups & CRM tab's date-range picker can scope the queue to a created-date cohort
-- (the frontend SUMs the in-window months). (The big status-less pool is mostly a bulk
-- import — surfaced as crm_kpi.queue_unassigned, not exploded here.) Frontend leads on
-- NEW + unassigned.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_lead_queue` AS
SELECT
  FORMAT_TIMESTAMP('%Y-%m', c.hs_created_at)          AS created_month,
  c.lead_status,
  COALESCE(o.owner_name,
           IF(c.owner_id IS NULL OR c.owner_id = '', 'Unassigned', 'Inactive owner')) AS owner_name,
  (c.owner_id IS NULL OR c.owner_id = '')             AS unassigned,
  COUNT(*)                                            AS contacts,
  COUNTIF(c.is_unworked)                              AS unworked,
  COUNTIF(c.is_app_signup)                            AS signups,
  -- sort priority so NEW floats to the top of the queue
  CASE c.lead_status
    WHEN 'NEW' THEN 1 WHEN 'OPEN' THEN 2 WHEN 'ATTEMPTED_TO_CONTACT' THEN 3
    WHEN 'IN_PROGRESS' THEN 4 WHEN 'OPEN_DEAL' THEN 5 WHEN 'UNQUALIFIED' THEN 6 ELSE 9
  END                                                 AS status_rank
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts` c
LEFT JOIN `bidbrain-analytics.client_resetdata.hubspot_owners` o
  ON c.owner_id = o.owner_id
WHERE c.lead_status IS NOT NULL          -- sales-touched pipeline only
  AND NOT c.is_customer
GROUP BY created_month, c.lead_status, owner_name, unassigned, status_rank
ORDER BY status_rank, contacts DESC;
