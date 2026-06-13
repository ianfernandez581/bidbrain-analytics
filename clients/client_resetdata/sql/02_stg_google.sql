-- ResetData — staged Google Ads (paid search — the "Always On" keyword campaigns).
--
-- Source is the native BigQuery Data Transfer Service table raw_google_ads.perf_google_ads
-- (NOT Windsor). The ResetData slice is account_name = 'Reset Data' (this DTS table also
-- carries client_slug = 'reset-data', but the account name is the stable key). EDA: 100%
-- campaign_type = SEARCH, 22 campaigns, currency AUD.
--
-- CURRENCY TRAP RESOLVED: this DTS loader has ALREADY converted micros → currency, so the
-- `spend` column is in whole AUD dollars (verified: ~$8 CPM over 1.59M imps). Do NOT divide
-- by 1,000,000. conversions / conversions_value come straight from Google Ads' own tracking
-- (83 conversions to date — the most reliable platform-reported conversion of the three).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_google` AS
SELECT
  metric_date,
  campaign_name           AS campaign,
  currency_code           AS currency,
  impressions             AS imps,
  clicks,
  spend                   AS spend_aud,     -- already AUD (DTS converted micros); see header
  conversions,
  conversions_value       AS conv_value
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE account_name = 'Reset Data';
