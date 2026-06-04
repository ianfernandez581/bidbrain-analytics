-- HireRight - staged The Trade Desk (programmatic air-cover). Campaign names are
-- persona / TAL, not geo, so market is a flat 'Global'.
--
-- The HireRight TradeDesk filter lives here once: ADVERTISER_NAME = 'HireRight'
-- (exact match - valid as-is in BigQuery). The mirror has BOTH an IMPRESSIONS and a
-- legacy IMPRESSION column, so impressions are COALESCE(IMPRESSIONS, IMPRESSION).
--
-- TradeDesk is billed in AUD, so spend is converted to the USD reporting currency at
-- the shared FX constant (FX_AUD_USD = 0.65 - see stg_dv360 header). The CASE keeps
-- it robust if a USD row ever appears.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_tradedesk` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  'Global'                                 AS market,
  MEDIA_TYPE                               AS media_type,
  AD_TYPE                                  AS ad_type,
  COALESCE(IMPRESSIONS, IMPRESSION)        AS imps,
  CLICKS                                   AS clicks,
  -- AUD -> USD @0.65 (TradeDesk is AUD today), else already USD.
  CASE CURRENCY WHEN 'AUD' THEN COSTS * 0.65 ELSE COSTS END AS spend_usd,
  TOTAL_CLICK_PLUS_VIEW_CONVERSIONS        AS conversions,
  CURRENCY                                 AS currency
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'HireRight';
