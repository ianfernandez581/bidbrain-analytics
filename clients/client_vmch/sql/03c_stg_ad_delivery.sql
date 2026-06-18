-- VMCH — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per campaign × day. This is the single source for the Campaign
-- filter AND (since 2026-06-18) for the time-series/KPI views (04/05/12/30 read their TTD
-- numbers from here, not stg_ttd) so MODELLED April flows everywhere consistently.
-- Future-proof: if another ad platform is added, UNION it here. Spend is AUD.
--
-- Two parts:
--   1) Measured TTD (stg_ttd) — but the stray Apr-2026 RAC/SAH slivers are EXCLUDED, because
--      their full April delivery is supplied as the modelled month (03b). Disability's real
--      April delivery (and everything from May on) is kept untouched.
--   2) Modelled April for RAC + SAH (03b, total ÷ 30 per day). See 03b for the why.
-- The whole-flight ad-group / creative views read stg_ttd directly, so they stay 100%
-- measured — the modelled month has no ad-group/creative granularity to break down.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ad_delivery` AS
SELECT
  'ttd'                     AS platform,
  campaign                  AS campaign,
  metric_date,
  CAST(NULL AS STRING)      AS market,       -- no geo dimension for VMCH
  ad_group_name,
  creative_name,
  imps,
  clicks,
  spend_aud,
  post_view_conv,    -- TTD post-view (view-through) attributed conversions
  post_click_conv    -- TTD post-click attributed conversions
FROM `bidbrain-analytics.client_vmch.stg_ttd`
WHERE NOT (                                  -- drop stray Apr slivers; 03b supplies modelled April
  metric_date BETWEEN DATE '2026-04-01' AND DATE '2026-04-30'
  AND campaign IN ('RAC_AU_ID Digital_VMCH_2026', 'SAH_AU_ID Digital_VMCH_2026')
)
UNION ALL
SELECT
  platform, campaign, metric_date, market, ad_group_name, creative_name,
  imps, clicks, spend_aud, post_view_conv, post_click_conv
FROM `bidbrain-analytics.client_vmch.stg_april_modelled`;