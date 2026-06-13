-- PropTrack (Transmission) — staged The Trade Desk delivery (the May–Jun 2026 Banking-ABM burst).
--
-- The TradeDesk filter lives here once: ADVERTISER_NAME = 'PopTrack' (TradeDesk spells the
-- client "PopTrack", LinkedIn spells it "PropTrack" — same client, use each source's spelling).
-- Spend is native AUD (COSTS) — there is NO FX conversion anywhere in this client.
--
-- ⚠️ Impressions come from IMPRESSION (singular). IMPRESSIONS (plural) is entirely NULL for
-- this advertiser — using it would zero the whole programmatic tab.
--
-- `segment` = the ABM audience: AD_GROUP_NAME with the campaign prefix stripped
-- (PARTNER-BROKER-DISTRIBUTION, LENDING-BANKING, MARKETING, TAL_ABM_DM, CREDIT-RISK).
-- `creative_size` = AD_TYPE (e.g. 728x90, 300x250, 480x360). `media_type` = Display | Video.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.stg_tradedesk` AS
SELECT
  DAY AS metric_date,
  CAMPAIGN_NAME AS campaign_name,
  MEDIA_TYPE    AS media_type,
  REGEXP_REPLACE(AD_GROUP_NAME, r'^PROPTRACK_BANKING-ABM_MAY-JUN2026_(DISPLAY|VIDEO)_AU_', '') AS segment,
  AD_TYPE       AS creative_size,
  IMPRESSION    AS imps,                       -- singular! IMPRESSIONS (plural) is NULL here
  CLICKS        AS clicks,
  COSTS         AS spend_aud,                  -- native AUD, no FX
  CLICK_CONVERSION                  AS click_conv,
  VIEW_THROUGH_CONVERSION           AS vt_conv,
  TOTAL_CLICK_PLUS_VIEW_CONVERSIONS AS conversions
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'PopTrack';
