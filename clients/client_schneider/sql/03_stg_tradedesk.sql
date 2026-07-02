-- Schneider Electric (APAC, via Transmission) — staged The Trade Desk (programmatic).
--
-- The Schneider TradeDesk filter lives here once: ADVERTISER_NAME = 'Schneider Electric'.
-- The mirror has BOTH an IMPRESSIONS and a legacy IMPRESSION column, so impressions are
-- COALESCE(IMPRESSIONS, IMPRESSION). Spend is converted to AUD at the shared FX constants
-- (FX_USD_AUD = 1.50, FX_SGD_AUD = 1.15 — see stg_dv360 header); TradeDesk is currently
-- all AUD, so the ELSE branch is what fires today, but the CASE keeps it robust.
--
-- market is parsed from AD_GROUP_NAME first, then CAMPAIGN_NAME (TradeDesk carries no geo
-- column). The ad group is the FINER grain: several ANZ-level campaigns (e.g. EBA
-- 'SE_EBA_Activate_AWR_June4', AirSeT 'SE AirSeT_ANZ_HighImpact...') split their AU vs NZ
-- delivery across ad groups (..._Australia_... / ..._NewZealand_... , or ..._AU_... /
-- ..._NZ_...) while the campaign name has no country — so reading the campaign name alone
-- stranded that spend in 'Unmapped'. Ad-group tokens therefore win; the campaign-name arms
-- (same parser as stg_linkedin) are the fallback. Country tokens win over coarse region
-- tokens; ANZ wins over Pacific. First match wins. Else → 'Unmapped'.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_tradedesk` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  MEDIA_TYPE                               AS media_type,
  AD_TYPE                                  AS ad_type,
  CASE
    -- (1) ad-group-level country (finer grain than the campaign; 'NewZealand' has no space)
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(AD_GROUP_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])NZ([ _-]|$)') OR REGEXP_CONTAINS(AD_GROUP_NAME, r'(?i)New ?Zealand') THEN 'New Zealand'
    -- (2) campaign-level fallback (IDENTICAL to stg_linkedin)
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])NZ([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)New ?Zealand') THEN 'New Zealand'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'INDIA') THEN 'India'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Indonesia') THEN 'Indonesia'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Malaysia') THEN 'Malaysia'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Singapore') THEN 'Singapore'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Thailand') THEN 'Thailand'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Vietnam') THEN 'Vietnam'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)Philippines') THEN 'Philippines'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(JP|JAPAN)([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Japan') THEN 'Japan'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'MEA') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(UAE|KSA)([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Saudi|Qatar|Egypt|Emirates)') THEN 'MEA'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SAM') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Brazil|Chile|Argentina|Mexico|Colombia|South America|LATAM)') THEN 'South America'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SEA') THEN 'SEA'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])ANZ([ _-]|$)') THEN 'ANZ'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Pacific') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])PAC([ _-]|$)') THEN 'Pacific'
    ELSE 'Unmapped'
  END                                      AS market,
  COALESCE(IMPRESSIONS, IMPRESSION)        AS imps,
  CLICKS                                   AS clicks,
  CASE CURRENCY
    WHEN 'USD' THEN COSTS * 1.50
    WHEN 'SGD' THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS spend_aud,
  TOTAL_CLICK_PLUS_VIEW_CONVERSIONS        AS conversions,
  CURRENCY                                 AS currency
FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
WHERE ADVERTISER_NAME = 'Schneider Electric';
