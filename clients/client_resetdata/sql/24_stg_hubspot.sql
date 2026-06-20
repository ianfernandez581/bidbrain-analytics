-- 24_stg_hubspot.sql — typed, flag-derived Contact base for the Signups & CRM tab.
-- Reads the shared raw mirror raw_windsor.hubspot_contacts (all-STRING, account 45274177
-- = Reset Data's only HubSpot) and casts + normalises + derives the funnel flags ONCE so
-- every CRM rollup below reads from here. (Numeric/count fields arrive as "1.0" strings, so
-- cast via FLOAT64 before INT64.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_hubspot_contacts` AS
WITH base AS (
  SELECT
    contact_hs_object_id                                   AS contact_id,
    LOWER(TRIM(contact_email))                             AS email,
    contact_company                                        AS company,
    contact_jobtitle                                       AS job_title,
    contact_country                                        AS country,
    contact_industry                                       AS industry,
    contact_hubspot_owner_id                               AS owner_id,

    -- lifecycle, normalised to canonical labels (source casing varies)
    CASE LOWER(TRIM(contact_lifecyclestage))
      WHEN 'lead' THEN 'Lead'
      WHEN 'subscriber' THEN 'Subscriber'
      WHEN 'marketingqualifiedlead' THEN 'MQL'
      WHEN 'salesqualifiedlead' THEN 'SQL'
      WHEN 'opportunity' THEN 'Opportunity'
      WHEN 'customer' THEN 'Customer'
      WHEN 'evangelist' THEN 'Evangelist'
      WHEN 'other' THEN 'Other'
      WHEN '' THEN NULL ELSE contact_lifecyclestage
    END                                                    AS lifecycle_stage,
    NULLIF(UPPER(TRIM(contact_hs_lead_status)), '')        AS lead_status,
    (LOWER(contact_hs_is_unworked) = 'true')               AS is_unworked,

    -- source / attribution (HubSpot Original Source + click ids)
    NULLIF(UPPER(TRIM(contact_hs_analytics_source)), '')   AS original_source,
    contact_hs_analytics_source_data_1                     AS source_detail_1,
    contact_hs_analytics_first_touch_converting_campaign   AS first_touch_campaign,
    contact_hs_analytics_last_touch_converting_campaign    AS last_touch_campaign,
    NULLIF(TRIM(contact_hs_google_click_id), '')           AS gclid,
    NULLIF(TRIM(contact_hs_facebook_click_id), '')         AS fbclid,

    -- timestamps: HubSpot create vs Reset Data APP signup
    SAFE_CAST(contact_createdate AS TIMESTAMP)             AS hs_created_at,
    SAFE_CAST(contact_rd_created_at AS TIMESTAMP)          AS rd_signup_at,
    SAFE_CAST(contact_rd_last_login AS TIMESTAMP)          AS rd_last_login_at,

    -- billing / spend / usage (the custom contact_rd_* family)
    SAFE_CAST(contact_rd_billing_balance AS FLOAT64)       AS rd_billing_balance,
    SAFE_CAST(contact_rd_total_spend AS FLOAT64)           AS rd_total_spend,
    SAFE_CAST(contact_rd_total_api_calls AS FLOAT64)       AS rd_total_api_calls,
    (LOWER(contact_rd_has_payment_method) = 'true')        AS rd_has_payment_method,

    -- deal rollups
    CAST(SAFE_CAST(contact_num_associated_deals AS FLOAT64) AS INT64) AS num_associated_deals,
    SAFE_CAST(contact_total_revenue AS FLOAT64)            AS total_revenue
  FROM `bidbrain-analytics.raw_windsor.hubspot_contacts`
)
SELECT
  *,
  -- friendly source bucket
  CASE original_source
    WHEN 'OFFLINE' THEN 'Offline / Sales'
    WHEN 'DIRECT_TRAFFIC' THEN 'Direct'
    WHEN 'ORGANIC_SEARCH' THEN 'Organic Search'
    WHEN 'PAID_SEARCH' THEN 'Paid Search'
    WHEN 'PAID_SOCIAL' THEN 'Paid Social'
    WHEN 'SOCIAL_MEDIA' THEN 'Organic Social'
    WHEN 'EMAIL_MARKETING' THEN 'Email'
    WHEN 'REFERRALS' THEN 'Referral'
    WHEN 'AI_REFERRALS' THEN 'AI Referral'
    WHEN 'OTHER_CAMPAIGNS' THEN 'Other Campaigns'
    WHEN NULL THEN 'Unknown'
    ELSE COALESCE(INITCAP(REPLACE(original_source, '_', ' ')), 'Unknown')
  END                                                      AS source_bucket,
  -- the funnel flags (single source of truth for every rollup)
  (rd_signup_at IS NOT NULL)                               AS is_app_signup,
  (rd_billing_balance > 0)                                 AS loaded_balance,
  (rd_total_spend > 0)                                     AS is_paying,
  (num_associated_deals > 0)                               AS has_deal,
  (gclid IS NOT NULL OR fbclid IS NOT NULL)                AS has_ad_click_id,
  (lifecycle_stage = 'Customer')                           AS is_customer
FROM base;
