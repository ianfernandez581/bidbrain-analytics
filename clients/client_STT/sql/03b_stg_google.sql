-- STT GDC — staged Google Ads (paid search — the "Always On" keyword campaigns).
--
-- The STT Google Ads filter lives here once: ACCOUNT_ID IN ('1641370256','4825242697')
-- (the USD + SGD customer accounts; 2026-08-06, replacing CAMPAIGN_NAME LIKE '%STT%' -
-- verified row-identical on switch day: 49,648 rows / $100,333.17 / 22 campaigns either
-- way). Scope on the IDs, never the names: account 4825242697's NAME was itself renamed
-- 'STT GDC_SGD' -> 'STT Global Data' on 2026-05-31, and campaign names are not stable
-- keys repo-wide (AGENTS.md). Like the other platforms it flips account mid-flight (USD
-- account "STT (USD)" Jun–Aug 2025, then SGD from Sep 2025), so COSTS is MIXED currency
-- — convert the USD rows to SGD at the same FX the rest of the dashboard uses (1.34).
-- The market is encoded in the campaign name (…_AlwaysOn26_<MARKET>_Keywords… /
-- …_DemandNurture_…), mapped to the same labels as GA4 / DV360.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_google` AS
SELECT
  DAY AS metric_date,
  CAMPAIGN_NAME AS campaign_name,
  ACCOUNT_NAME AS account_name,
  CURRENCY AS currency,
  CASE REGEXP_EXTRACT(CAMPAIGN_NAME, r'_(?:AlwaysOn26|DemandNurture)_([A-Z]{2})_')
    WHEN 'SG' THEN 'Singapore'
    WHEN 'MY' THEN 'Malaysia'
    WHEN 'IN' THEN 'India'
    WHEN 'PH' THEN 'Philippines'
    WHEN 'ID' THEN 'Indonesia'
    WHEN 'TH' THEN 'Thailand'
    WHEN 'VN' THEN 'Vietnam'
    WHEN 'JP' THEN 'Japan'
    WHEN 'KR' THEN 'Korea'
    ELSE 'Other'
  END AS market,
  IMPRESSIONS AS imps,
  CLICKS AS clicks,
  COSTS AS cost_native,
  IF(CURRENCY = 'USD', COSTS * 1.34, COSTS) AS spend_sgd,
  CONVERSIONS AS conversions
FROM `bidbrain-analytics.raw_snowflake.google_ads_apac`
WHERE ACCOUNT_ID IN ('1641370256', '4825242697');
