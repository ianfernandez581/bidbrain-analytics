-- PropTrack (Transmission) — staged The Trade Desk delivery (the May–Jun 2026 Banking-ABM burst).
--
-- The TradeDesk filter lives here once: LOWER(TRIM(ADVERTISER_NAME)) IN ('poptrack','proptrack').
-- TTD originally spelled the client "PopTrack"; the platform corrected the advertiser name to
-- "PropTrack" on 2026-07-22 (misspelled rows stop 07-21, corrected rows start 07-22 - the date
-- ranges are DISJOINT, so spanning both spellings cannot double-count). Name-keyed because
-- tradedesk_apac_all has NO advertiser-id column (the TTD UI id is gb75r2p - switch to it if the
-- mirror ever grows the column). LinkedIn spells it "PropTrack" - same client, per-source spelling.
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
WHERE LOWER(TRIM(ADVERTISER_NAME)) IN ('poptrack', 'proptrack');
