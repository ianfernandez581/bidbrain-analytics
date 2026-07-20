-- Schneider Electric "Liquid AI Data Center" (LQAIDC) — staged LinkedIn Ads (paid social).
--
-- This is a SINGLE, self-contained campaign dashboard (NOT the multi-program Schneider Pacific
-- dashboard): the LQAIDC TOFU / Awareness push for "Liquid Cooling for AI Data Centers", running
-- LinkedIn + The Trade Desk across 6 countries. Objective = Website visits (awareness), so there are
-- NO leads / conversions here — it is a reach + clicks + CTR story.
--
-- Scope filter: the Schneider LinkedIn account (SchneiderElectric_TransmissionSG%) AND the campaign
-- name contains 'LQAIDC'. NB: LinkedIn's mirror uses CAMPAIGN_NAME at the AD-SET grain (the country
-- ad set, e.g. SE_LQAIDC_LI_India_TOFU_May26) and CAMPAIGN_GROUP_NAME for the group. The group name
-- was renamed mid-flight (SE_LQAIDC_LI_TOFU_May26 -> 2306_SE_LQAIDC_LI_TOFU_May26 on ~2026-07-07),
-- so we key on the STABLE ad-set CAMPAIGN_NAME (which always carries 'LQAIDC' + the country) — that
-- rolls up both group-name forms cleanly.
--
-- Country is parsed from the ad-set CAMPAIGN_NAME (LinkedIn carries no geo column). The 6 countries:
-- India, Brazil, Australia, Chile, Saudi Arabia (KSA token), UAE. The concept is the AD_TITLE (the 3
-- creative messages LC1/LC2/LC3). Spend is AUD: the LQAI account is _AUD (COSTS already AUD); the
-- account-suffix CASE keeps it robust if a _USD/_SGD account ever appears (USD@1.50, SGD@1.15).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.stg_linkedin` AS
SELECT
  DATE(DAY)                                AS metric_date,
  'linkedin'                               AS platform,
  CAMPAIGN_ID                              AS adset_id,
  CAMPAIGN_NAME                            AS adset_name,
  CASE
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'India')     THEN 'India'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Brazil')    THEN 'Brazil'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Chile')     THEN 'Chile'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])KSA([ _-]|$)')
         OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Saudi')  THEN 'Saudi Arabia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])UAE([ _-]|$)')
         OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Emirates') THEN 'UAE'
    ELSE 'Other'
  END                                      AS country,
  -- creative message = the ad title (LC1 Performance / LC2 AI Heat / LC3 Coolant Flow). Single-image
  -- Sponsored Content (CREATIVE_TYPE STANDARD); no video on this campaign.
  COALESCE(NULLIF(TRIM(AD_TITLE), ''), 'Sponsored Content') AS concept,
  'Single image'                           AS creative_format,
  CREATIVE_NAME                            AS creative_name,
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  CASE
    WHEN ENDS_WITH(ACCOUNT_NAME, '_USD') THEN COSTS * 1.50
    WHEN ENDS_WITH(ACCOUNT_NAME, '_SGD') THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS spend_aud
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'
  AND UPPER(CAMPAIGN_NAME) LIKE '%LQAIDC%';
