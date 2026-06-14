-- TLM — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per platform × campaign × day, folding Google Ads + The Trade Desk into
-- the SAME shape so the campaign-grained roll-ups (ad_campaigns / ad_campaign_monthly /
-- ad_campaign_weekly) can be built once on top of it. TLM has only two paid channels (Google +
-- TTD — no Meta, no GA4), so this is leaner than ResetData's three-platform version.
--
-- Currency: spend_aud is AUD for both — Google already AUD, TTD's stg view passes AUD through
-- (FX case at 1.50 is present but unused since Windsor delivers AUD for TLM).
-- conversions + revenue come from Google only (TTD reports anonymous pixel fires, no revenue).
-- creative = TTD ad_format (or creative_name); NULL for Google.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.stg_ad_delivery` AS
SELECT
  'google'              AS platform,
  campaign,
  metric_date,
  CAST(NULL AS STRING)  AS creative,
  imps,
  clicks,
  spend_aud,
  conversions,
  revenue
FROM `bidbrain-analytics.client_tlm.stg_google`
UNION ALL
SELECT
  'ttd'                 AS platform,
  campaign,
  metric_date,
  ad_format             AS creative,
  imps,
  clicks,
  spend_aud,
  CAST(NULL AS NUMERIC) AS conversions,   -- TTD pixel fires are anonymous (no revenue)
  CAST(NULL AS NUMERIC) AS revenue        -- TTD reports no attributable revenue
FROM `bidbrain-analytics.client_tlm.stg_ttd`;