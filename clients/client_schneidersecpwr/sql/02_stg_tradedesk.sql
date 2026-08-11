-- Schneider Electric "Secure Power" — staged The Trade Desk (programmatic display).
--
-- Same three-brief scope and the same disjoint token sets as 01_stg_linkedin (see that file's header
-- for why each token exists — in particular why `2305_` alone is not sufficient for software_first,
-- and why ind_edge is deliberately Wave-3 only). Advertiser filter: ADVERTISER_NAME = 'Schneider
-- Electric' (the Snowflake TTD mirror has NO advertiser/campaign ID columns — names only, which is
-- exactly why every match here is a substring token and never a fixed offset).
--
-- MARKET is resolved AD GROUP FIRST, then campaign name — the same two-stage parser client_schneider
-- uses, and it matters here: Industrial Edge and Software First carry their country only in the AD
-- GROUP name (e.g. an `..._AWR_2026` campaign whose ad groups split AU vs NZ), so a campaign-name-only
-- parse would strand that delivery. Enterprise IT is the opposite — its region sits in the campaign
-- name (`SE_EntIT_2026_S2_{MEA,India,SAM}`) with no country token at all, which is why markets are
-- NOT folded to Australia/New Zealand on this dashboard.
--
-- Impressions = COALESCE(IMPRESSIONS, IMPRESSION): the mirror carries both spellings. Spend is AUD
-- (CURRENCY is AUD today; the USD@1.50 / SGD@1.15 arms are kept for robustness).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.stg_tradedesk` AS
WITH scoped AS (
  SELECT
    *,
    CASE
      WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'EntIT') THEN 'ent_it'
      WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'SE_Industrial Edge_')
        OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Industrial Edge Wave3')
        OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Industrial Edge W3')
        OR STARTS_WITH(TRIM(CAMPAIGN_NAME), '2463_') THEN 'ind_edge'
      WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Software First')
        OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'EcoStruxureIT')
        OR STARTS_WITH(TRIM(CAMPAIGN_NAME), '2305_') THEN 'software_first'
      ELSE NULL
    END AS campaign
  FROM `bidbrain-analytics.raw_snowflake.tradedesk_apac_all`
  WHERE ADVERTISER_NAME = 'Schneider Electric'
)
SELECT
  DATE(DAY)                                AS metric_date,
  'tradedesk'                              AS platform,
  campaign,
  CAMPAIGN_NAME                            AS adset_name,
  AD_GROUP_NAME                            AS group_name,
  CASE
    -- (1) ad-group-level country - the finer grain, and the only place Industrial Edge /
    --     Software First carry AU vs NZ.
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(AD_GROUP_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(AD_GROUP_NAME), r'(^|[ _-])NZ([ _-]|$)') OR REGEXP_CONTAINS(AD_GROUP_NAME, r'(?i)New ?Zealand') THEN 'New Zealand'
    -- (2) campaign-level fallback - IDENTICAL parser to stg_linkedin.
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])NZ([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)New ?Zealand') THEN 'New Zealand'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'INDIA') THEN 'India'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(JP|JAPAN)([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Japan') THEN 'Japan'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'MEA') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(UAE|KSA)([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Saudi|Qatar|Egypt|Emirates)') THEN 'MEA'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SAM') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Brazil|Chile|Argentina|Mexico|Colombia|South America|LATAM)') THEN 'South America'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SEA') THEN 'SEA'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])ANZ([ _-]|$)') THEN 'ANZ'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Pacific') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])PAC([ _-]|$)') THEN 'Pacific'
    ELSE 'Unmapped'
  END                                      AS market,
  -- Display creative: the concept is the creative name (no consistent concept token across these
  -- three briefs, unlike LQAIDC's AccelAI/CoolPerf codes), the format is the banner size.
  COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), '(unnamed)') AS concept,
  COALESCE(NULLIF(TRIM(AD_TYPE), ''), MEDIA_TYPE)        AS creative_format,
  COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), '(unnamed)') AS creative_name,
  COALESCE(IMPRESSIONS, IMPRESSION)        AS imps,
  CLICKS                                   AS clicks,
  CASE CURRENCY
    WHEN 'USD' THEN COSTS * 1.50
    WHEN 'SGD' THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS spend_aud,
  -- Trade Desk has no lead-form concept. NULL (not 0) so the dashboard can hide the metric rather
  -- than draw a real zero - same contract as client_schneider's stg_ad_delivery.
  CAST(NULL AS INT64)                      AS leads,
  CAST(NULL AS INT64)                      AS lead_form_opens
FROM scoped
WHERE campaign IS NOT NULL;
