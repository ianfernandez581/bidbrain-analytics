-- City Perfume — The Trade Desk staging (filter the shared raw layer once, here).
--
-- Source: bidbrain-analytics.raw_windsor.perf_the_trade_desk, advertiser_name='City Perfume'.
-- Small upper-funnel DISPLAY awareness pilot: 105 rows, 1 campaign, ~AUD 1,044 spend,
-- 2026-05-17..05-31. ALL AUD. No video inventory (all video_* are 0).
--
-- `conversions` is a JSON column but DOUBLE-ENCODED: it holds a JSON *string* scalar
-- (or a JSON null on 45/105 rows), NOT a native object. A naive JSON_EXTRACT on the raw
-- column silently returns 0/NULL for everything — you MUST PARSE_JSON(JSON_VALUE(...))
-- first. We surface the `_03` attribution window (the only consistently populated one):
-- conversion_touch_03 = total/multi-touch (=397 over the flight), with the click/view
-- split available. These are view-through/multi-touch DSP attribution counts only —
-- there is NO revenue/value in the JSON, so TTD never contributes platform_revenue.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_ttd` AS
SELECT
  campaign_name,
  ad_format,
  metric_date,
  impressions                       AS imps,
  clicks,
  cost                              AS spend_aud,
  COALESCE(SAFE_CAST(JSON_VALUE(SAFE.PARSE_JSON(JSON_VALUE(conversions)), '$.conversion_touch_03')      AS FLOAT64), 0) AS conversions,
  COALESCE(SAFE_CAST(JSON_VALUE(SAFE.PARSE_JSON(JSON_VALUE(conversions)), '$.click_conversion_03')       AS FLOAT64), 0) AS click_conversions,
  COALESCE(SAFE_CAST(JSON_VALUE(SAFE.PARSE_JSON(JSON_VALUE(conversions)), '$.view_through_conversion_03') AS FLOAT64), 0) AS view_conversions
FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
WHERE advertiser_name = 'City Perfume'
  AND metric_date >= DATE '2025-06-01';
