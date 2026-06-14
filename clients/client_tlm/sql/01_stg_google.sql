-- TLM — staged Google Ads (paid search + shopping + Performance Max).
--
-- Source is the native BigQuery Data Transfer Service table raw_google_ads.perf_google_ads
-- (NOT Windsor). The TLM slice is account_name = 'The Little Marionette'. EDA: campaign_type
-- present (PERFORMANCE_MAX / SEARCH / SHOPPING), currency AUD, 20+ campaigns, conversions
-- and conversions_value (revenue) populated — this is the e-commerce money source.
--
-- CURRENCY TRAP RESOLVED: this DTS loader has ALREADY converted micros → currency, so the
-- `spend` column is in whole AUD dollars (verified: CPM ~$23.97). Do NOT divide by 1,000,000.
-- conversions = purchases (Google Ads tracked); conversions_value = revenue (AUD) — the ROAS
-- numerator. ROAS / AOV / CPA are derived client-side, never stored here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.stg_google` AS
SELECT
  metric_date,
  campaign_name           AS campaign,
  campaign_type,
  currency_code           AS currency,
  impressions             AS imps,
  clicks,
  spend                   AS spend_aud,     -- already AUD (DTS converted micros); see header
  conversions,                              -- purchases (NUMERIC)
  conversions_value       AS revenue         -- AUD; the ROAS numerator
FROM `bidbrain-analytics.raw_google_ads.perf_google_ads`
WHERE account_name = 'The Little Marionette';