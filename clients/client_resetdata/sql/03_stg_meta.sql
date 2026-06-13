-- ResetData — staged Meta paid social (the awareness / lead-gen driver).
--
-- The ResetData filter lives here once: account_name = 'Reset backup – Ad account'
-- (note the EN-DASH "–", not a hyphen "-"). EDA: this is the ONLY Reset account on Meta —
-- there is NO separate "primary" account, the "backup" name notwithstanding. Its
-- client_slug is 'resetdata' (no hyphen), unlike Google Ads / GA4 which use 'reset-data',
-- so the account name is the stable key here.
--
-- Currency is already AUD (currency = 'AUD'), so `cost` maps straight to spend_aud — no FX.
-- Objective is uniformly OUTCOME_LEADS; `leads` is the platform-reported conversion (very
-- sparse to date — 2 leads — flagged in the README). creative_name / creative_title power
-- the creative-mix view. landing_page_views + link_clicks kept as soft engagement signals.
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
  cost                                            AS spend_aud,   -- already AUD
  leads                                           AS conversions  -- platform-reported leads
FROM `bidbrain-analytics.raw_windsor.perf_meta`
WHERE account_name = 'Reset backup – Ad account';
