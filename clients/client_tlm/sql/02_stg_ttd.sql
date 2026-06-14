-- TLM — staged The Trade Desk programmatic display.
--
-- The TLM filter lives here once: advertiser_name = 'The Little Marionette'. EDA: 1 campaign
-- across 6 ad formats, flight Apr 2026 →, currency AUD (Windsor already AUD — not USD).
-- video_starts/video_completes are 0 (no video creative); conversions JSON is non-null but
-- anonymous — pixel fires with no revenue attribution, surfaced only as a callout.
--
-- CURRENCY: EDA shows currency = 'AUD' for all rows. The CASE keeps us robust if a USD row
-- ever lands (multiply by 1.50, the shared FX_USD_AUD constant). Since Windsor already
-- delivers AUD, the CASE passes it through unchanged.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.stg_ttd` AS
SELECT
  metric_date,
  campaign_name                                   AS campaign,
  ad_format,
  creative_name,
  currency,
  impressions                                     AS imps,
  clicks,
  CASE currency
    WHEN 'USD' THEN cost * 1.50                    -- USD → AUD @1.50 (FX_USD_AUD)
    ELSE cost                                      -- already AUD (all TLM rows per EDA)
  END                                             AS spend_aud,
  video_starts,
  video_25,
  video_50,
  video_75,
  video_completes
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE advertiser_name = 'The Little Marionette';