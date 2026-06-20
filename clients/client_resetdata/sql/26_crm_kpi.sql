-- 26_crm_kpi.sql — ONE-row headline funnel + queue counts for the Signups & CRM tab.
-- The signup funnel Caroline cares about: Leads -> App signups -> Loaded balance -> Paying.
-- (Time-based cuts "this week / QTD" are derived frontend-side from crm_signups_weekly.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_kpi` AS
SELECT
  COUNT(*)                                        AS leads,                 -- all HubSpot contacts
  COUNTIF(is_app_signup)                          AS app_signups,           -- created an app.reset.ai account
  COUNTIF(loaded_balance)                         AS loaded_balance,        -- rd_billing_balance > 0
  COUNTIF(is_paying)                              AS paying,                -- rd_total_spend > 0
  COUNTIF(is_app_signup AND NOT is_paying)        AS signups_not_paying,    -- free signups only
  COUNTIF(is_customer)                            AS customers,             -- lifecycle = Customer
  COUNTIF(has_deal)                               AS with_deal,             -- >=1 associated deal
  ROUND(SUM(IF(loaded_balance, rd_billing_balance, 0)), 2)  AS total_balance,
  ROUND(SUM(IF(is_paying, rd_total_spend, 0)), 2)           AS total_rd_spend,
  ROUND(SUM(total_revenue), 0)                    AS total_hs_revenue,
  -- BDM queue: new + untriaged leads (non-customers)
  COUNTIF(lead_status = 'NEW')                                            AS queue_new,
  COUNTIF((owner_id IS NULL OR owner_id = '') AND NOT is_customer)        AS queue_unassigned,
  COUNTIF(lead_status = 'NEW' AND (owner_id IS NULL OR owner_id = ''))    AS queue_new_unassigned,
  -- freshness of the CRM slice
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', MAX(rd_signup_at))  AS last_signup_at,
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', MAX(hs_created_at)) AS last_contact_at
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`;
