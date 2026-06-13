-- STT GDC — staged DV360 programmatic display (the always-on prospecting driver).
--
-- The STT DV360 filter lives here once: ADVERTISER_ID IN ('7572338345','6466367438'),
-- which carries the FY25-26 Always On programmatic flight across the 9 APAC markets
-- (two delivering campaigns — "…Nov-Feb…" and "…2025-2026Q12_25…" — plus a few
-- zero-delivery shells). Spend is already SGD (CURRENCY = 'SGD').
--
-- Spend = REVENUE_ADV_CURRENCY: in DV360 this is the advertiser-billed cost
-- (media + fees), i.e. what STT actually paid — the figure stakeholders expect,
-- not the bare MEDIA_COST. COUNTRY_NAME is a 2-letter code → mapped to the same
-- market labels as GA4 so the two line up. CAMPAIGN_NAME is carried through so the
-- dashboard's Campaign filter can slice DV360 delivery client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_dv360` AS
SELECT
  DAY AS metric_date,
  CAMPAIGN_NAME AS campaign_name,
  CASE COUNTRY_NAME
    WHEN 'SG' THEN 'Singapore'
    WHEN 'MY' THEN 'Malaysia'
    WHEN 'IN' THEN 'India'
    WHEN 'PH' THEN 'Philippines'
    WHEN 'ID' THEN 'Indonesia'
    WHEN 'TH' THEN 'Thailand'
    WHEN 'VN' THEN 'Vietnam'
    WHEN 'JP' THEN 'Japan'
    WHEN 'KR' THEN 'Korea'
    ELSE COALESCE(COUNTRY_NAME, 'Other')
  END AS market,
  IMPRESSIONS AS imps,
  CLICKS AS clicks,
  IF(CURRENCY = 'USD', REVENUE_ADV_CURRENCY * 1.34, REVENUE_ADV_CURRENCY) AS spend_sgd,  -- any USD advertiser → SGD @1.34
  CONVERSIONS_TOTAL AS conversions,
  CURRENCY AS currency
FROM `bidbrain-analytics.raw_snowflake.dv360_apac`
WHERE ADVERTISER_ID IN ('7572338345', '6466367438');
