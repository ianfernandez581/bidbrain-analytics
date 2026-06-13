-- PropTrack (Transmission) — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per platform × campaign × day, folding the two paid channels (The Trade
-- Desk programmatic + LinkedIn paid social) into the SAME shape so the campaign-grained roll-ups
-- (ad_campaigns / ad_campaign_monthly / ad_campaign_daily) can be built once on top of it. The
-- dashboard sums the selected campaigns client-side to rescale every combined ad-delivery figure.
--
-- Currency: spend_aud is native AUD for both platforms — no FX anywhere.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.stg_ad_delivery` AS
SELECT
  'tradedesk'   AS platform,
  campaign_name AS campaign,
  metric_date,
  imps,
  clicks,
  spend_aud,
  conversions
FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
UNION ALL
SELECT
  'linkedin'    AS platform,
  campaign_name AS campaign,
  metric_date,
  imps,
  clicks,
  spend_aud,
  conversions
FROM `bidbrain-analytics.client_proptrack.stg_linkedin`;
