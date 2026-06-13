-- ResetData — staged The Trade Desk programmatic display.
--
-- The ResetData filter lives here once: advertiser_name = 'ResetData'. EDA: 1 campaign
-- (ResetData_Apr26) across three standard display sizes (300x600 / 300x250 / 728x90 in
-- ad_format), short flight (mid-May 2026 →), client_slug 'resetdata' (no hyphen).
--
-- CURRENCY TRAP RESOLVED: TTD bills in USD (currency = 'USD'), so cost is converted to the
-- AUD reporting currency at the shared fixed rate FX_USD_AUD = 1.50 (the same constant used
-- by client_schneider; surfaced in `kpi`). The CASE keeps it robust if an AUD row ever lands.
-- conversions upstream is a JSON blob that is NULL for every ResetData row — TTD reports no
-- usable conversions, so none are emitted (the README notes this gap). ad_format = creative size.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_ttd` AS
SELECT
  metric_date,
  campaign_name                                   AS campaign,
  ad_format,
  currency,
  impressions                                     AS imps,
  clicks,
  CASE currency
    WHEN 'USD' THEN cost * 1.50                    -- USD → AUD @1.50 (FX_USD_AUD)
    ELSE cost                                      -- already AUD
  END                                             AS spend_aud
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE advertiser_name = 'ResetData';
