-- VMCH — staged The Trade Desk programmatic display.
--
-- The VMCH filter lives here once: advertiser_name = 'VMCH ' (with trailing space).
-- Cost is ALREADY in AUD (advertiser_currency_code = 'AUD' upstream), so NO FX
-- conversion is applied — the reporting currency IS AUD. No geo/market column exists
-- in the source (VMCH is AU-only), so market is omitted from the staging layer.
-- Carries ad_group_name and creative_name for the Paid Media breakdowns.
-- One spend field: CAST(cost AS NUMERIC) AS spend_aud.
--
-- ATTRIBUTED CONVERSIONS (the real "attributable leads" — post-view + post-click):
-- The Windsor `conversions` column is a double-encoded JSON string holding The Trade Desk's
-- attribution: view_through_conversion_NN (post-view), click_conversion_NN (post-click) and
-- conversion_touch_NN (TOTAL pixel fires — deliberately NOT used; it counts ALL site activity on
-- the tracker, ~3.3k, the vast majority NOT ad-attributed, so it would massively overstate "leads").
--
-- STRUCTURE (verified against the live data): VMCH has THREE distinct conversion trackers, each
-- exported as a PAIR of attribution columns — {01,02}, {03,04}, {05,06}. CLICK counts are byte-
-- identical within each pair (cc01==cc02==3, cc03==cc04==6, cc05==cc06==4, zero row-level mismatches),
-- which proves each pair is one tracker reported twice — so post-click = 3+6+4 = 13 is EXACT. VIEW-
-- THROUGH differs within a pair by attribution setting/window (vt 62/69, 19/21, 32/5), so the post-
-- view total is window-dependent (~95–113); we take ONE consistent column per tracker — the first of
-- each pair {01,03,05} = 113. Summing all six columns would double-count the three trackers. Net
-- flight totals: ~113 post-view, ~13 post-click (post-view rightly dominates for upper-funnel display).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ttd` AS
WITH base AS (
  SELECT *, PARSE_JSON(JSON_VALUE(conversions)) AS _conv
  FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
  WHERE advertiser_name = 'VMCH '
)
SELECT
  metric_date,
  campaign_name                                               AS campaign,
  ad_group_name,
  creative_name,
  ad_format,
  impressions                                                 AS imps,
  clicks,
  CAST(cost AS NUMERIC)                                       AS spend_aud,
  CAST(NULL AS NUMERIC)                                       AS conversions,  -- legacy slot; real attribution below
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_01') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_05') AS FLOAT64), 0) ) AS post_view_conv,
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_01') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_05') AS FLOAT64), 0) ) AS post_click_conv
FROM base;