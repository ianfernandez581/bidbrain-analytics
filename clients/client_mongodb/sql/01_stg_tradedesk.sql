-- stg_tradedesk: MongoDB's Trade Desk slice, SCOPE-PINNED to seed_campaign_ids.
--
-- 2026-08-05 - CAMPAIGN SCOPE PIN. Scope + PROGRAMME/MARKET now come from
-- client_mongodb.seed_campaign_ids (targets/campaign_ids.csv, the committed mirror of
-- Transmission's campaign-reference sheet, which carries the TTD campaign IDs 4l7ib47 etc.).
-- The delivery mirror (raw_snowflake.tradedesk_apac_all) has NO campaign-id column - names
-- only - so the seed is joined on the NORMALISED campaign name (brief-number prefix stripped
-- on BOTH sides; the same campaign exists under both '2265_MONGODB_...' and 'MONGODB_...'
-- forms in the feed and both must land on one seed row). The join:
--   * pins the dashboard to exactly the sheet's campaigns (an unseeded campaign is EXCLUDED,
--     never silently included - the status dashboard's scope-drift check + this job's log
--     warning surface it instead of the dash absorbing it);
--   * carries CAMPAIGN_ID onto every row (the stable anchor names can't provide);
--   * takes PROGRAMME (IDC/IDE) + MARKET from the seed, so a future rename can shift name
--     tokens without silently re-tagging delivery (the 2026-08-04 '2265_' defect class).
-- STRATEGY/OBJECTIVE stay name-parsed off the *_NORM fields (ad-group grain / cosmetic).
--
-- 2026-08-04 - BRIEF-NUMBER PREFIX FIX (kept): the fixed-offset SPLIT parsing broke when the
-- '2265_' prefix landed ~2026-07-06 (PROGRAMME read '2026-Q2', MARKET 'DEMAND-GENERATION'),
-- silently dropping 1,394,967 imps / $11,906.04 from every paid KPI and mis-tagging rows to
-- KGA(IDC). See AGENTS.md "Campaign names are NOT stable keys" for the repo-wide rule.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_tradedesk` AS
SELECT r.DAY, r.CAMPAIGN_NAME, r.AD_GROUP_NAME, r.CREATIVE_FORMAT, r.PUBLISHER,
  r.IMPRESSIONS, r.COSTS, r.CLICKS, r.CONVERSIONS,
  s.PROGRAMME,
  s.MARKET,
  SPLIT(r.AD_GROUP_NAME_NORM, "_")[SAFE_OFFSET(6)] AS STRATEGY,
  SPLIT(r.CAMPAIGN_NAME_NORM, "_")[SAFE_OFFSET(4)] AS OBJECTIVE,
  s.CAMPAIGN_ID
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
) r
JOIN (
  SELECT CAMPAIGN_ID, PROGRAMME, MARKET,
         REGEXP_REPLACE(TRIM(CAMPAIGN_NAME), r'^[0-9]+_', '') AS CAMPAIGN_NAME_NORM
  FROM `bidbrain-analytics.client_mongodb.seed_campaign_ids`
  WHERE PLATFORM = "tradedesk"
) s USING (CAMPAIGN_NAME_NORM)
