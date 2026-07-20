-- Schneider Electric "Liquid AI Data Center" (LQAIDC) — staged The Trade Desk (programmatic display).
--
-- Scope filter: ADVERTISER_NAME = 'Schneider Electric' AND the campaign name contains 'LQAIDC'. The
-- TTD mirror has NO id columns (names only) and its campaign name was renamed mid-flight
-- (SE_LQAIDC_TTD_TOFU_May26 -> 2306_SE_LQAIDC_TTD_TOFU_May26 on ~2026-07-06), so the '%LQAIDC%'
-- substring rolls up both forms. Impressions = COALESCE(IMPRESSIONS, IMPRESSION) (the mirror carries
-- both). Spend is AUD (CURRENCY is AUD today; USD@1.50 / SGD@1.15 CASE kept for robustness).
--
-- Country is parsed from AD_GROUP_NAME (the finer grain; e.g. SE_LQAIDC_TTD_India_TOFU_May26). The
-- creative concept is parsed from CREATIVE_NAME (4 concepts: Accelerate AI / Cooling Performance /
-- Cool & Smart / Every Degree, some untagged = Generic); the format is AD_TYPE (banner size).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_tradedesk` AS
SELECT
  DATE(DAY)                                AS metric_date,
  'tradedesk'                              AS platform,
  CAMPAIGN_NAME                            AS campaign_name,
  AD_GROUP_NAME                            AS adgroup_name,
  CASE
    WHEN CONTAINS_SUBSTR(AD_GROUP_NAME, 'India')     THEN 'India'
    WHEN CONTAINS_SUBSTR(AD_GROUP_NAME, 'Brazil')    THEN 'Brazil'
    WHEN CONTAINS_SUBSTR(AD_GROUP_NAME, 'Australia') THEN 'Australia'
    WHEN CONTAINS_SUBSTR(AD_GROUP_NAME, 'Chile')     THEN 'Chile'
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])KSA([ _-]|$)')
         OR CONTAINS_SUBSTR(AD_GROUP_NAME, 'Saudi')  THEN 'Saudi Arabia'
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])UAE([ _-]|$)')
         OR CONTAINS_SUBSTR(AD_GROUP_NAME, 'Emirates') THEN 'UAE'
    ELSE 'Other'
  END                                      AS country,
  CASE
    WHEN CONTAINS_SUBSTR(CREATIVE_NAME, 'AccelAI')   THEN 'Accelerate AI'
    WHEN CONTAINS_SUBSTR(CREATIVE_NAME, 'CoolPerf')  THEN 'Cooling Performance'
    WHEN CONTAINS_SUBSTR(CREATIVE_NAME, 'CoolSmart') THEN 'Cool & Smart'
    WHEN CONTAINS_SUBSTR(CREATIVE_NAME, 'EveryDeg')  THEN 'Every Degree'
    ELSE 'Generic'
  END                                      AS concept,
  COALESCE(NULLIF(TRIM(AD_TYPE), ''), MEDIA_TYPE) AS creative_format,
  CREATIVE_NAME                            AS creative_name,
  COALESCE(IMPRESSIONS, IMPRESSION)        AS imps,
  CLICKS                                   AS clicks,
  CASE CURRENCY
    WHEN 'USD' THEN COSTS * 1.50
    WHEN 'SGD' THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS spend_aud
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'Schneider Electric'
  AND UPPER(CAMPAIGN_NAME) LIKE '%LQAIDC%';
