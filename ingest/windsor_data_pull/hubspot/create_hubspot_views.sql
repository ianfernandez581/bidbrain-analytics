-- Starter TYPED views over the all-STRING raw HubSpot mirror, for the Reset Data dashboard.
-- Raw tables are lossless STRING; these views SAFE_CAST the dashboard's key metrics/dates.
-- Apply with:  bq query --use_legacy_sql=false --location=australia-southeast1 < create_hubspot_views.sql

CREATE OR REPLACE VIEW `bidbrain-analytics.raw_windsor.v_hubspot_contacts` AS
SELECT
  -- identity / join keys
  contact_hs_object_id                                   AS contact_id,
  contact_email                                          AS email,
  contact_work_email                                     AS work_email,
  contact_hs_email_domain                                AS email_domain,
  contact_firstname                                      AS first_name,
  contact_lastname                                       AS last_name,
  contact_company                                        AS company,
  contact_rd_business_name                               AS rd_business_name,
  contact_jobtitle                                       AS job_title,
  contact_phone                                          AS phone,
  contact_country                                        AS country,
  contact_state                                          AS state,
  contact_city                                           AS city,
  contact_industry                                       AS industry,
  contact_company_size                                   AS company_size,

  -- lifecycle / status / owner
  contact_lifecyclestage                                 AS lifecycle_stage,
  contact_hs_lead_status                                 AS lead_status,
  contact_hubspot_owner_id                               AS owner_id,
  contact_hubspot_team_id                                AS team_id,
  SAFE_CAST(contact_hs_predictivecontactscore_v2 AS FLOAT64) AS likelihood_to_close,

  -- source / attribution
  contact_hs_analytics_source                            AS original_source,
  contact_hs_analytics_source_data_1                     AS original_source_detail_1,
  contact_hs_analytics_source_data_2                     AS original_source_detail_2,
  contact_hs_analytics_first_referrer                    AS first_referrer,
  contact_hs_analytics_last_referrer                     AS last_referrer,
  contact_hs_analytics_first_url                         AS first_page_seen,
  contact_hs_analytics_first_touch_converting_campaign   AS first_touch_campaign,
  contact_hs_analytics_last_touch_converting_campaign    AS last_touch_campaign,
  contact_hs_google_click_id                             AS gclid,
  contact_hs_facebook_click_id                           AS fbclid,
  contact_source                                         AS contact_source,

  -- signup / creation / time (HubSpot create vs RD-app signup)
  SAFE_CAST(contact_createdate AS TIMESTAMP)             AS hs_created_at,
  SAFE_CAST(contact_rd_created_at AS TIMESTAMP)          AS rd_signup_at,        -- app.resetdata.ai signup
  SAFE_CAST(contact_rd_last_login AS TIMESTAMP)          AS rd_last_login_at,
  SAFE_CAST(contact_rd_last_api_call AS TIMESTAMP)       AS rd_last_api_call_at,
  SAFE_CAST(contact_first_conversion_date AS TIMESTAMP)  AS first_conversion_at,
  contact_first_conversion_event_name                    AS first_conversion_event,
  SAFE_CAST(contact_recent_conversion_date AS TIMESTAMP) AS recent_conversion_at,

  -- billing / spend / app usage (the custom contact_rd_* family)
  SAFE_CAST(contact_rd_billing_balance AS FLOAT64)       AS rd_billing_balance,  -- == RdBillingBalance
  SAFE_CAST(contact_rd_total_spend AS FLOAT64)           AS rd_total_spend,
  SAFE_CAST(contact_rd_total_api_calls AS FLOAT64)       AS rd_total_api_calls,
  contact_rd_billing_mode                                AS rd_billing_mode,
  contact_rd_has_payment_method                          AS rd_has_payment_method,
  contact_rd_is_active                                   AS rd_is_active,
  contact_rd_onboarded                                   AS rd_onboarded,
  SAFE_CAST(contact_rd_workspace_count AS FLOAT64)       AS rd_workspace_count,

  -- deal / conversion rollups (contact level)
  CAST(SAFE_CAST(contact_num_associated_deals AS FLOAT64) AS INT64) AS num_associated_deals,
  (SAFE_CAST(contact_num_associated_deals AS FLOAT64) > 0) AS has_deal,         -- ROI flag
  SAFE_CAST(contact_total_revenue AS FLOAT64)            AS total_revenue,
  SAFE_CAST(contact_recent_deal_amount AS FLOAT64)       AS recent_deal_amount,
  SAFE_CAST(contact_first_deal_created_date AS TIMESTAMP) AS first_deal_created_at,
  CAST(SAFE_CAST(contact_num_conversion_events AS FLOAT64) AS INT64) AS num_form_submissions,

  client_slug, agency_slug, _pulled_at
FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`;

CREATE OR REPLACE VIEW `bidbrain-analytics.raw_windsor.v_hubspot_deals` AS
SELECT
  deal_hs_object_id                                      AS deal_id,
  deal_dealname                                          AS deal_name,
  SAFE_CAST(deal_amount AS FLOAT64)                      AS amount,
  SAFE_CAST(deal_amount_in_home_currency AS FLOAT64)     AS amount_home_ccy,
  deal_currency_code                                     AS currency,
  deal_dealstage                                         AS deal_stage,
  deal_pipeline                                          AS pipeline,
  deal_dealtype                                          AS deal_type,
  SAFE_CAST(deal_hs_arr AS FLOAT64)                      AS arr,
  SAFE_CAST(deal_hs_mrr AS FLOAT64)                      AS mrr,
  SAFE_CAST(deal_hs_acv AS FLOAT64)                      AS acv,
  SAFE_CAST(deal_hs_tcv AS FLOAT64)                      AS tcv,
  SAFE_CAST(deal_hs_forecast_amount AS FLOAT64)          AS forecast_amount,
  SAFE_CAST(deal_hs_forecast_probability AS FLOAT64)     AS forecast_probability,
  SAFE_CAST(deal_createdate AS TIMESTAMP)                AS created_at,
  SAFE_CAST(deal_closedate AS TIMESTAMP)                 AS close_at,
  deal_closed_won_reason                                 AS won_reason,
  deal_closed_lost_reason                                AS lost_reason,
  deal_hs_analytics_source                               AS original_source,
  deal_hubspot_owner_id                                  AS owner_id,
  CAST(SAFE_CAST(deal_num_associated_contacts AS FLOAT64) AS INT64) AS num_associated_contacts,
  client_slug, agency_slug, _pulled_at
FROM `bidbrain-analytics.raw_windsor.hubspot_deals`;
