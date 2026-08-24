-- HireRight - staged The Trade Desk (programmatic air-cover). Campaign names are
-- persona / TAL, not geo, and the mirror carries no region column, so `market` is a
-- flat 'Global' (same honesty caveat as stg_linkedin - do not invent geo from a name
-- you have not looked at).
--
-- The HireRight TradeDesk filter lives here once: ADVERTISER_NAME = 'HireRight'
-- (exact match - valid as-is in BigQuery, and the only one of the three filters that
-- is not a substring match). The mirror has BOTH an IMPRESSIONS and a legacy
-- IMPRESSION column, so impressions are COALESCE(IMPRESSIONS, IMPRESSION).
--
-- TradeDesk is billed in AUD, so spend is converted to the USD reporting currency at
-- the shared rate from the `fx` view (00_fx.sql). The CASE keeps it robust if a USD
-- row ever appears.
--
-- CAMPAIGN NAMES ARE NOT STABLE KEYS (repo-wide rule): the brief-number prefix is
-- stripped into its own `brief` column - see 01_stg_dv360's header for why.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.stg_tradedesk` AS
SELECT
  DATE(t.DAY)                              AS metric_date,
  REGEXP_REPLACE(TRIM(t.CAMPAIGN_NAME), r'^[0-9]+_', '')  AS campaign_name,
  NULLIF(REGEXP_EXTRACT(TRIM(t.CAMPAIGN_NAME), r'^([0-9]+)_'), '') AS brief,
  t.CAMPAIGN_NAME                          AS campaign_name_raw,
  'Global'                                 AS market,
  'Global'                                 AS region,
  t.MEDIA_TYPE                             AS media_type,
  t.AD_TYPE                                AS ad_type,
  COALESCE(t.IMPRESSIONS, t.IMPRESSION)    AS imps,
  t.CLICKS                                 AS clicks,
  -- AUD -> USD at the shared rate (TradeDesk is AUD today), else already USD.
  CASE t.CURRENCY WHEN 'AUD' THEN t.COSTS * fx.aud_usd ELSE t.COSTS END AS spend_usd,
  -- TradeDesk pixel conversions (post-click + post-view). A DIFFERENT definition from
  -- DV360 Floodlight and from a LinkedIn lead - see 04_stg_ad_delivery.
  t.TOTAL_CLICK_PLUS_VIEW_CONVERSIONS      AS attr_conv,
  t.CURRENCY                               AS currency
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all` t
CROSS JOIN `bidbrain-analytics.client_hireright.fx` fx
WHERE t.ADVERTISER_NAME = 'HireRight';
