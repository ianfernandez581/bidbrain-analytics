-- ResetData — CRM outcomes as a DAILY time series, for the Overview hero chart's trend lines
-- ("Ad spend & its effects": spend bars vs sessions + confirmed leads + paying customers over time).
--
-- The HubSpot snapshot (raw_windsor.hubspot_contacts) carries per-contact LIFECYCLE dates, so even
-- though the table is a current-state snapshot we can reconstruct WHEN each contact reached a stage:
--   * confirmed leads  = contact_hs_lifecyclestage_lead_date      (dense: ~4,651 of 4,701 contacts)
--   * paying customers = contact_hs_lifecyclestage_customer_date  (the ~71 who reached Customer; the
--     rd_total_spend>0 "paying" flag (64) has NO date, so the Customer-stage date is the closest dated
--     proxy for "became a paying customer" — labelled as such in the dashboard).
-- Dates are ISO strings ('2024-02-15T22:50:30.173Z'); the first 10 chars are YYYY-MM-DD.
-- Grain = one row per day; the dashboard buckets to month/week/day and aligns to the hero's timeline.
-- NB: whole-account CRM (NOT scoped by the ad platform/campaign/date filters), same as the CRM tab.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_outcomes_daily` AS
WITH ev AS (
  SELECT SAFE_CAST(SUBSTR(contact_hs_lifecyclestage_lead_date, 1, 10) AS DATE) AS day, 1 AS is_lead, 0 AS is_customer
  FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`
  WHERE NULLIF(contact_hs_lifecyclestage_lead_date, '') IS NOT NULL
  UNION ALL
  SELECT SAFE_CAST(SUBSTR(contact_hs_lifecyclestage_customer_date, 1, 10) AS DATE), 0, 1
  FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`
  WHERE NULLIF(contact_hs_lifecyclestage_customer_date, '') IS NOT NULL
)
SELECT
  day,
  SUM(is_lead)     AS new_leads,       -- contacts that became a Lead that day
  SUM(is_customer) AS new_customers    -- contacts that became a Customer (paying) that day
FROM ev
WHERE day IS NOT NULL
GROUP BY day
ORDER BY day;
