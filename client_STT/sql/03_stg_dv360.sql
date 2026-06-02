-- STT GDC — staged DV360 programmatic display (the always-on prospecting driver).
--
-- The STT DV360 filter lives here once: the single Always On campaign
-- "(APAC) - STTGDC_Always On_Nov-Feb - (JN1663)", which ran Nov 2025 → May 2026
-- across the 9 APAC markets. Spend is already SGD (CURRENCY = 'SGD').
--
-- Spend = REVENUE_ADV_CURRENCY: in DV360 this is the advertiser-billed cost
-- (media + fees), i.e. what STT actually paid — the figure stakeholders expect,
-- not the bare MEDIA_COST. COUNTRY_NAME is a 2-letter code → mapped to the same
-- market labels as GA4 so the two line up.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.stg_dv360` AS
SELECT
  DAY AS metric_date,
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
  REVENUE_ADV_CURRENCY AS spend_sgd,
  CONVERSIONS_TOTAL AS conversions,
  CURRENCY AS currency
FROM `bidbrain-analytics.raw_snowflake.dv360_apac`
WHERE CAMPAIGN_NAME = '(APAC) - STTGDC_Always On_Nov-Feb - (JN1663)';
