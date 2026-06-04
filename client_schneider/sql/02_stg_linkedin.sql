-- Schneider Electric (APAC, via Transmission) — staged LinkedIn Ads (paid social).
--
-- The Schneider LinkedIn filter lives here once: ACCOUNT_NAME ILIKE
-- 'SchneiderElectric_TransmissionSG%' (three accounts observed: _USD, _AUD, _SGD).
-- LinkedIn has NO currency column, so the reporting currency is inferred from the
-- account-name suffix and converted to AUD at the shared FX constants
-- (FX_USD_AUD = 1.50, FX_SGD_AUD = 1.15 — see stg_dv360 header).
--
-- market is parsed from CAMPAIGN_NAME (LinkedIn carries no geo column). The observed
-- region tokens are AU / NZ / ANZ / Australia, India, SEA + SEA countries, MEA + UAE/KSA,
-- SAM / Brazil / Chile, Japan, Pacific / PAC. Anything else → 'Unmapped'. CREATIVE_TYPE
-- is labelled for the creative-mix chart (STANDARD = single image; NULL/'' = video/other).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_linkedin` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  ACCOUNT_NAME                             AS account_name,
  CASE
    WHEN CREATIVE_TYPE = 'STANDARD' THEN 'Sponsored Content'
    WHEN CREATIVE_TYPE IS NULL OR CREATIVE_TYPE = '' THEN 'Video / Other'
    ELSE CREATIVE_TYPE
  END                                      AS creative_type,
  -- market parsed from the campaign name (case-insensitive; delimiter-aware for the short
  -- codes so 'AU' can't match inside a word). FINE-grained so the AU/NZ split survives;
  -- country tokens win over the coarse region tokens, ANZ wins over Pacific (Pacific-program
  -- campaigns are ANZ-targeted). First match wins. Identical parser in stg_tradedesk.
  CASE
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])NZ([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'New Zealand') THEN 'New Zealand'
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
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  -- _USD → AUD @1.50, _SGD → AUD @1.15, else (e.g. _AUD) already AUD. cost_aud holds AUD.
  -- ENDS_WITH on the account-name suffix (no LIKE/ESCAPE ambiguity).
  CASE
    WHEN ENDS_WITH(ACCOUNT_NAME, '_USD') THEN COSTS * 1.50
    WHEN ENDS_WITH(ACCOUNT_NAME, '_SGD') THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS cost_aud,
  VIDEO_VIEWS                              AS video_views,
  VIDEO_STARTS                             AS video_starts,
  VIDEO_COMPLETIONS                        AS video_completions,
  ENGAGEMENTS                              AS engagements,
  LEADS                                    AS leads,
  LEAD_FORM_OPENS                          AS lead_form_opens,
  LINK_CLICKS                              AS link_clicks,
  ACTION_CLICKS                            AS action_clicks
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%';
