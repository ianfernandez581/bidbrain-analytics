-- VMCH — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per campaign × day, from TTD only. This is a pass-through
-- of stg_ttd (at the campaign grain already), shaped to match the stg_ad_delivery
-- contract so the campaign-grained roll-ups (ad_campaigns / ad_campaign_monthly /
-- ad_campaign_weekly) can be built once on top of it. Future-proof: if another
-- ad platform is added, UNION it here. Spend is AUD.
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
FROM `bidbrain-analytics.client_vmch.stg_ttd`;