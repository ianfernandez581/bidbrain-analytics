-- HireRight - unified ad-delivery base (the single source for the Campaign filter
-- and every campaign-grained roll-up). One long-format row per platform x campaign x
-- day, folding DV360, TradeDesk and LinkedIn into the SAME shape so ad_campaigns /
-- ad_campaign_monthly / ad_campaign_weekly / ad_campaign_market are built once on top.
-- Mirrors client_STT/sql/03c_stg_ad_delivery.sql.
--
-- spend_usd is USD for all three (each stg_* view already converted to USD).
-- market: DV360 carries real geo (country); TradeDesk + LinkedIn are 'Global'
-- air-cover. creative_type is LinkedIn-only (NULL elsewhere). conversions = the
-- platform's native conversion metric (DV360 CONVERSIONS_TOTAL, TradeDesk
-- click+view conversions, LinkedIn LEADS - its closest conversion).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_ad_delivery` AS
SELECT
  'dv360'                   AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_usd,
  conversions
FROM `bidbrain-analytics.client_hireright.stg_dv360`
UNION ALL
SELECT
  'tradedesk'               AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  CAST(NULL AS STRING)      AS creative_type,
  imps,
  clicks,
  spend_usd,
  conversions
FROM `bidbrain-analytics.client_hireright.stg_tradedesk`
UNION ALL
SELECT
  'linkedin'                AS platform,
  campaign_name             AS campaign,
  metric_date,
  market,
  creative_type,
  imps,
  clicks,
  cost_usd                  AS spend_usd,   -- cost_usd already holds USD (see stg_linkedin)
  leads                     AS conversions  -- LinkedIn's closest conversion metric
FROM `bidbrain-analytics.client_hireright.stg_linkedin`;
