-- VMCH — staged The Trade Desk programmatic display.
--
-- The VMCH filter lives here once: advertiser_name = 'VMCH ' (with trailing space).
-- Cost is ALREADY in AUD (advertiser_currency_code = 'AUD' upstream), so NO FX
-- conversion is applied — the reporting currency IS AUD. No geo/market column exists
-- in the source (VMCH is AU-only), so market is omitted from the staging layer.
-- Carries ad_group_name and creative_name for the Paid Media breakdowns.
-- One spend field: CAST(cost AS NUMERIC) AS spend_aud.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ttd` AS
SELECT
  metric_date,
  campaign_name                                               AS campaign,
  ad_group_name,
  creative_name,
  ad_format,
  impressions                                                 AS imps,
  clicks,
  CAST(cost AS NUMERIC)                                       AS spend_aud,
  CAST(NULL AS NUMERIC)                                       AS conversions   -- TTD conversions are NULL for VMCH
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE advertiser_name = 'VMCH ';