-- 26b_crm_kpi_monthly.sql — the crm_kpi funnel + queue counts, but broken out by the
-- month each contact was CREATED in HubSpot (FORMAT_TIMESTAMP over hs_created_at). This
-- backs the Signups & CRM tab's date-range picker: the frontend SUMs the in-window months
-- to scope the whole funnel to a created-date cohort ("leads created in the window ->
-- signed up -> loaded balance -> paying"), matching how the ad tabs scope KPIs at month grain.
-- Every metric is a COUNTIF/SUM over contacts and each contact has exactly one created month,
-- so summing all months reproduces the all-time crm_kpi exactly. Contacts with a NULL created
-- month land in the NULL bucket (included only at "All time", excluded once a range is picked).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.crm_kpi_monthly` AS
SELECT
  FORMAT_TIMESTAMP('%Y-%m', hs_created_at)        AS created_month,
  COUNT(*)                                        AS leads,                 -- HubSpot contacts created that month
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
  COUNTIF(lead_status = 'NEW' AND (owner_id IS NULL OR owner_id = ''))    AS queue_new_unassigned
FROM `bidbrain-analytics.client_resetdata.stg_hubspot_contacts`
GROUP BY created_month
ORDER BY created_month;
