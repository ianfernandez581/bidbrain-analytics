-- STT GDC — unified ad-delivery base (the single source for the Campaign filter).
--
-- One long-format row per platform × campaign × day, folding the three paid
-- channels (Google Ads paid search, DV360 programmatic display, LinkedIn paid
-- social) into the SAME shape so the campaign-grained roll-ups (ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly / ad_campaign_market) can be built once
-- on top of it. Mirrors how the GA4 market-grained views power the Country filter.
--
-- Currency: spend_sgd is SGD for all three. Google + DV360 already convert USD rows
-- in their stg_* views; LinkedIn's stg_linkedin.cost_usd already holds SGD too (the
-- USD account is multiplied by FX at staging), so it is aliased straight to spend_sgd.
-- market is the GA4/DV360 market label for Google + DV360 and NULL for LinkedIn
-- (LinkedIn isn't charted by market); creative_type is LinkedIn-only (NULL elsewhere).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_ad_delivery` AS
SELECT
  'google'                  AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_sgd
FROM `bidbrain-analytics.client_stt.stg_google`
UNION ALL
SELECT
  'dv360'                   AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_sgd
FROM `bidbrain-analytics.client_stt.stg_dv360`
UNION ALL
SELECT
  'linkedin'                AS platform,
  campaign_name             AS campaign,
  metric_date,
  CAST(NULL AS STRING)      AS market,
  creative_type,
  imps,
  clicks,
  cost_usd                  AS spend_sgd   -- cost_usd already holds SGD (see stg_linkedin)
FROM `bidbrain-analytics.client_stt.stg_linkedin`;
