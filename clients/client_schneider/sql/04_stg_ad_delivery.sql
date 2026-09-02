-- Schneider Electric — unified ad-delivery base (the single source for the Campaign filter
-- and every campaign-grained roll-up). One long-format row per platform × campaign × day,
-- folding DV360, TradeDesk, LinkedIn and Google Search into the SAME shape so ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly / ad_campaign_market can be built once on top.
-- Mirrors client_STT/sql/03c_stg_ad_delivery.sql.
--
-- spend_aud is AUD for all four (each stg_* view already converted to AUD — Google Search at
-- the same shared FX_USD_AUD = 1.50 the others use, so the four are on one basis and CAN be
-- summed; see 03b_stg_google_search for why cost_usd is kept beside it). market is the
-- brief reporting region for all four (DV360 from COUNTRY_NAME; LinkedIn/TradeDesk/Search
-- parsed from CAMPAIGN_NAME). channel_objective is NULL for now (reserved — the brief leaves
-- it NULL until an objective convention is confirmed). creative_type is LinkedIn-only.
--
-- leads / lead_form_opens are LinkedIn-ONLY on-platform LEAD-FORM counts (LinkedIn's own
-- LEADS / LEAD_FORM_OPENS columns, carried through stg_linkedin). They are NOT Salesforce CS
-- leads and must never be added to a CS total — a paid-only program (EcoConsult) can report
-- lead-form leads with no Salesforce campaign at all. NULL (not 0) for DV360 / TradeDesk:
-- those staging views carry no conversion feed, so 0 would read as "measured none".
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_ad_delivery` AS
SELECT
  'dv360'                   AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(NULL AS FLOAT64)     AS leads,            -- DV360 carries no lead-form feed
  CAST(NULL AS FLOAT64)     AS lead_form_opens
FROM `bidbrain-analytics.client_schneider.stg_dv360`
UNION ALL
SELECT
  'tradedesk'               AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(NULL AS FLOAT64)     AS leads,            -- TradeDesk conversions not staged for SE
  CAST(NULL AS FLOAT64)     AS lead_form_opens
FROM `bidbrain-analytics.client_schneider.stg_tradedesk`
UNION ALL
SELECT
  'linkedin'                AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  creative_type,
  imps,
  clicks,
  cost_aud                  AS spend_aud,  -- cost_aud already holds AUD (see stg_linkedin)
  CAST(leads AS FLOAT64)            AS leads,
  CAST(lead_form_opens AS FLOAT64)  AS lead_form_opens
FROM `bidbrain-analytics.client_schneider.stg_linkedin`
UNION ALL
-- GOOGLE SEARCH (SEM), added 2026-09-02. Staged whole-account; scoped to the dashboard's programs
-- downstream in 20_pm_delivery via seed_campaign_map — this account also carries the non-Pacific
-- brief-2306 campaigns (Brazil / Chile / Saudi / UAE), which belong to client_schneiderlqai.
-- leads / lead_form_opens are NULL, not 0: Search has no lead-form feed at all, and the account's
-- CONVERSIONS column is quarantined as unresolved (see the 03b header — never derive a lead, a CPA
-- or a ROAS from it). 0 here would read as "measured none", which is a different and false claim.
SELECT
  'google_search'           AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_aud,
  CAST(NULL AS FLOAT64)     AS leads,            -- Search carries no lead-form feed
  CAST(NULL AS FLOAT64)     AS lead_form_opens
FROM `bidbrain-analytics.client_schneider.stg_google_search`;
