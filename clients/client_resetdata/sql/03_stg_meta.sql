-- ResetData — staged Meta paid social (the awareness / lead-gen driver).
--
-- The ResetData filter lives here once: account_name = 'Reset backup – Ad account'
-- (note the EN-DASH "–", not a hyphen "-"). EDA: this is the ONLY Reset account on Meta —
-- there is NO separate "primary" account, the "backup" name notwithstanding. Its
-- client_slug is 'resetdata' (no hyphen), unlike Google Ads / GA4 which use 'reset-data',
-- so the account name is the stable key here.
--
-- Currency is already AUD (currency = 'AUD'), so `cost` maps straight to spend_aud — no FX.
-- Objective is uniformly OUTCOME_LEADS. The platform-reported LEAD is the advertiser's custom
-- pixel conversion **"Signup Button"** (signup_button_conversions, ~51 across the flight) — the
-- deliberate lead tracker for this account. We use it as `conversions` instead of the generic
-- `leads` action (actions_lead), which is near-zero noise here (2). creative_name /
-- creative_title power the creative-mix view; landing_page_views + link_clicks are soft signals.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_meta` AS
SELECT
  metric_date,
  campaign_name                                   AS campaign,
  COALESCE(NULLIF(creative_title, ''), NULLIF(creative_body, ''), NULLIF(creative_id, ''), '(unnamed)') AS creative_name,
  currency,
  impressions                                     AS imps,
  clicks,
  link_clicks,
  landing_page_views,
  cost                                            AS spend_aud,                -- already AUD
  signup_button_conversions                       AS conversions,              -- "Signup Button" custom pixel = the lead
  leads                                           AS platform_leads_actions    -- generic actions_lead (sparse; kept for reference)
FROM `bidbrain-analytics.raw_windsor.perf_meta`
WHERE account_name = 'Reset backup – Ad account';
