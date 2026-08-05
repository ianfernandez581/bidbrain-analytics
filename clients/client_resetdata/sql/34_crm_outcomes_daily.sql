-- ResetData — CRM outcomes as a DAILY time series, for the Overview hero chart's trend lines
-- ("Ad spend & its effects": spend bars vs leads + cost-per-lead + new paying customers over time).
--
-- The HubSpot snapshot (raw_windsor.hubspot_contacts) carries per-contact LIFECYCLE dates, so even
-- though the table is a current-state snapshot we can reconstruct WHEN each contact reached a stage:
--   * confirmed leads  = contact_hs_lifecyclestage_lead_date      (dense: ~4,651 of 4,701 contacts)
--   * lifecycle customers = contact_hs_lifecyclestage_customer_date (the ~77 who reached Customer —
--     kept for reference, but ~ZERO overlap with the real payers: sales never advances lifecycle
--     when a contact starts paying in the app, so payers mostly stay stage Lead)
--   * NEW PAYING CUSTOMERS (2026-08-05, the hero's line) = contacts with rd_total_spend > 0, dated
--     by hs_created_at — HubSpot records NO first-payment date (the rd_* family has only
--     created/last-login/last-api-call), so the contact CREATED date is the dated basis, chosen to
--     match the Signups & CRM tab (crm_signups_weekly / the whole created-date-cohort model). This
--     series SUMS to crm_kpi.paying exactly, so the hero line agrees with the headline card.
-- Lifecycle dates are ISO strings ('2024-02-15T22:50:30.173Z'); the first 10 chars are YYYY-MM-DD.
-- Grain = one row per day; the dashboard buckets to month/week/day and aligns to the hero's timeline.
-- NB: whole-account CRM (NOT scoped by the ad platform/campaign/date filters), same as the CRM tab.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_outcomes_daily` AS
WITH ev AS (
  SELECT SAFE_CAST(SUBSTR(contact_hs_lifecyclestage_lead_date, 1, 10) AS DATE) AS day,
         1 AS is_lead, 0 AS is_customer, 0 AS is_payer
  FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`
  WHERE NULLIF(contact_hs_lifecyclestage_lead_date, '') IS NOT NULL
  UNION ALL
  SELECT SAFE_CAST(SUBSTR(contact_hs_lifecyclestage_customer_date, 1, 10) AS DATE), 0, 1, 0
  FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`
  WHERE NULLIF(contact_hs_lifecyclestage_customer_date, '') IS NOT NULL
  UNION ALL
  SELECT DATE(hs_created_at), 0, 0, 1
  FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`
  WHERE is_paying AND hs_created_at IS NOT NULL
)
SELECT
  day,
  SUM(is_lead)     AS new_leads,       -- contacts that became a Lead that day
  SUM(is_customer) AS new_customers,   -- contacts that reached lifecycle Customer that day (reference)
  SUM(is_payer)    AS new_payers       -- paying contacts (rd_total_spend>0) by created day (the hero line)
FROM ev
WHERE day IS NOT NULL
GROUP BY day
ORDER BY day;
