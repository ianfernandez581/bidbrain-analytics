-- stg_tradedesk: MongoDB's Trade Desk slice + the campaign-name parsing.
--
-- 2026-08-04 - BRIEF-NUMBER PREFIX FIX (this was the OPEN DEFECT recorded in AGENTS.md).
-- On ~2026-07-06 the campaigns were renamed with a leading brief number ('2265_...'),
-- which shifts every underscore field one position. The FIXED offsets below then read
-- the wrong fields: PROGRAMME came back as '2026-Q2' and MARKET as 'DEMAND-GENERATION'.
-- Consequences, both silent:
--   * MARKET 'DEMAND-GENERATION' matches no market chip, so marketOk() dropped the rows
--     from every paid KPI, chart, CSV and AI deck - 1,394,967 imps / $11,906.04 of
--     2026-07-06..07-31 delivery.
--   * PROGRAMME '2026-Q2' contains neither 'IDE' nor 'DNB', so the dashboard's
--     campaignOf() ALSO mis-tagged those rows to KGA(IDC) instead of DNB.
-- FIX: strip the prefix once into CAMPAIGN_NAME_NORM / AD_GROUP_NAME_NORM and parse every
-- token off those. AD_GROUP_NAME was never renamed (so STRATEGY was unaffected), but it is
-- normalised too so the same rollout cannot break it later - verified a no-op on today's
-- data. Raw CAMPAIGN_NAME / AD_GROUP_NAME are still carried through for display.
-- See AGENTS.md "Campaign names are NOT stable keys" for the repo-wide rule.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_tradedesk` AS
SELECT DAY, CAMPAIGN_NAME, AD_GROUP_NAME, CREATIVE_FORMAT, PUBLISHER,
  IMPRESSIONS, COSTS, CLICKS, CONVERSIONS,
  SPLIT(CAMPAIGN_NAME_NORM, "_")[SAFE_OFFSET(2)] AS PROGRAMME,
  SPLIT(CAMPAIGN_NAME_NORM, "_")[SAFE_OFFSET(5)] AS MARKET,
  SPLIT(AD_GROUP_NAME_NORM, "_")[SAFE_OFFSET(6)] AS STRATEGY,
  SPLIT(CAMPAIGN_NAME_NORM, "_")[SAFE_OFFSET(4)] AS OBJECTIVE
FROM (
  -- Was client_mongodb.src_tradedesk (landed by the export job's TD_SQL).
  -- Now reads the shared raw mirror (snowflake_data_pull) and reproduces the
  -- old TD_SQL projection + advertiser filter here. IMPRESSIONS/CLICKS cast back
  -- to INT64 to match the old src_tradedesk schema.
  SELECT DAY, CAMPAIGN_NAME, AD_GROUP_NAME,
         REGEXP_REPLACE(TRIM(CAMPAIGN_NAME),  r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM,
         REGEXP_REPLACE(TRIM(AD_GROUP_NAME),  r'^[0-9]+_', '') AS AD_GROUP_NAME_NORM,
         AD_TYPE AS CREATIVE_FORMAT, PARTNER_NAME AS PUBLISHER,
         CAST(COALESCE(IMPRESSIONS, IMPRESSION) AS INT64) AS IMPRESSIONS,
         COSTS, CAST(CLICKS AS INT64) AS CLICKS,
         TOTAL_CLICK_PLUS_VIEW_CONVERSIONS AS CONVERSIONS
  FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
  WHERE ADVERTISER_NAME = "MongoDB"
)
