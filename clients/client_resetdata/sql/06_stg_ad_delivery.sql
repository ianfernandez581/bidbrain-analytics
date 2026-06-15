-- ResetData — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per platform × campaign × day, folding the four paid channels
-- (Google Ads paid search, Meta paid social, The Trade Desk programmatic display, Reddit
-- community awareness) into the SAME shape so the campaign-grained roll-ups (ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly) can be built once on top of it. Mirrors
-- client_STT's stg_ad_delivery.
--
-- Currency: spend_aud is AUD for all four — Google + Meta + Reddit are already AUD, TTD's stg
-- view converts USD→AUD @1.50. conversions is platform-reported (Google `conversions`, Meta
-- `leads`, Reddit sign-up + lead clicks); TTD reports none upstream, so 0. creative is the
-- per-platform creative dimension (Meta creative_name, TTD ad_format size, NULL for Google /
-- Reddit) — handy for slicing if needed.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.stg_ad_delivery` AS
SELECT
  'google'              AS platform,
  campaign,
  metric_date,
  CAST(NULL AS STRING)  AS creative,
  imps,
  clicks,
  spend_aud,
  conversions
FROM `bidbrain-analytics.client_resetdata.stg_google`
UNION ALL
SELECT
  'meta'                AS platform,
  campaign,
  metric_date,
  creative_name         AS creative,
  imps,
  clicks,
  spend_aud,
  CAST(conversions AS NUMERIC) AS conversions
FROM `bidbrain-analytics.client_resetdata.stg_meta`
UNION ALL
SELECT
  'ttd'                 AS platform,
  campaign,
  metric_date,
  ad_format             AS creative,
  imps,
  clicks,
  spend_aud,
  CAST(NULL AS NUMERIC) AS conversions   -- TTD reports no usable conversions (JSON null)
FROM `bidbrain-analytics.client_resetdata.stg_ttd`
UNION ALL
SELECT
  'reddit'              AS platform,
  campaign,
  metric_date,
  CAST(NULL AS STRING)  AS creative,
  imps,
  clicks,
  spend_aud,
  CAST(conversions AS NUMERIC) AS conversions   -- Reddit sign-up + lead clicks (sparse)
FROM `bidbrain-analytics.client_resetdata.stg_reddit`;
