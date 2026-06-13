-- Schneider Electric — unified ad-delivery base (the single source for the Campaign filter
-- and every campaign-grained roll-up). One long-format row per platform × campaign × day,
-- folding DV360, TradeDesk and LinkedIn into the SAME shape so ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly / ad_campaign_market can be built once on top.
-- Mirrors client_STT/sql/03c_stg_ad_delivery.sql.
--
-- spend_aud is AUD for all three (each stg_* view already converted to AUD). market is the
-- brief reporting region for all three (DV360 from COUNTRY_NAME; LinkedIn/TradeDesk parsed
-- from CAMPAIGN_NAME). channel_objective is NULL for now (reserved — the brief leaves it
-- NULL until an objective convention is confirmed). creative_type is LinkedIn-only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_ad_delivery` AS
SELECT
  'dv360'                   AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_aud
FROM `bidbrain-analytics.client_schneider.stg_dv360`
UNION ALL
SELECT
  'tradedesk'               AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_aud
FROM `bidbrain-analytics.client_schneider.stg_tradedesk`
UNION ALL
SELECT
  'linkedin'                AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS channel_objective,
  creative_type,
  imps,
  clicks,
  cost_aud                  AS spend_aud   -- cost_aud already holds AUD (see stg_linkedin)
FROM `bidbrain-analytics.client_schneider.stg_linkedin`;
