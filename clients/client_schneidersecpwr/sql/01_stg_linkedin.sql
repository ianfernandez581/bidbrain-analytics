-- Schneider Electric "Secure Power" — staged LinkedIn Ads (paid social).
--
-- A THREE-CAMPAIGN, paid-media-only dashboard (a sibling of client_schneiderlqai, NOT part of the
-- multi-program client_schneider Pacific dashboard). It reports the three Secure Power briefs that
-- are deliberately OUT of client_schneider's scope because they have separate stakeholders:
--     ent_it          Enterprise IT Expansion        brief 1958   (multi-region: India/MEA/SAM/Pacific)
--     ind_edge        Industrial Edge / Prefab       brief 2463   (Wave 3 only — see below)
--     software_first  Software First EcoStruxure     brief 2305
--
-- SELF-CONTAINED: reads the shared raw mirror directly, exactly like client_schneiderlqai. It does
-- NOT read client_schneider's views, so a scope change on that dashboard cannot move numbers here.
--
-- CAMPAIGN TAGGING — token matching on CAMPAIGN_NAME, never a fixed offset. Transmission is
-- progressively prefixing campaign names with the brief number, so the SAME campaign appears under
-- both `SE_*` and `<brief>_SE_*` forms; substring tokens roll both up (repo rule: "campaign names are
-- NOT stable keys", md/AGENTS.md). The three token sets are disjoint — verified against every
-- Schneider campaign before this view was written.
--   * ent_it: `EntIT` catches SE_EntIT_2026_* and 1958_SE_EntIT_2026_*.
--   * ind_edge: WAVE 3 ONLY. The bare token `Industrial Edge` would ALSO sweep in the 2025
--     `1839_Schneider_Electric_Pacific_*` wave (Sep-Dec 2025, ~A$8.7k) which is a different brief, so
--     the tokens are Wave-3 specific. Widen these ONLY on an explicit instruction.
--   * software_first: `2305_` ALONE IS NOT ENOUGH — the Trade Desk line ran as
--     `SE_EcoStruxureIT_AWR_2026` from 2026-06-17 and only gained the `2305_` prefix on 07-06, so a
--     prefix-only token silently drops ~A$2.3k. Hence the `EcoStruxureIT` token.
--
-- MATCH ON CAMPAIGN_NAME, NOT CAMPAIGN_GROUP_NAME. LinkedIn's group names are mislabelled here: a
-- group named `2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named
-- `2463_SE_Industrial Edge Wave3_*`. Keying on the group would cross-tag two different briefs.
--
-- MARKET is parsed from CAMPAIGN_NAME (LinkedIn carries no geo column) with the SAME parser
-- client_schneider uses — country tokens win over coarse region tokens, ANZ wins over Pacific, first
-- match wins, delimiter-aware short codes so 'AU' cannot match inside a word. Unlike
-- client_schneider's `pm_delivery`, markets are NOT folded to Australia/New Zealand here: Enterprise
-- IT genuinely runs across India / MEA / South America / Pacific and only ~12% of it is Pacific, so
-- folding would report the rest as Australia. Anything unparseable lands in 'Unmapped' and shows as a
-- loud chip rather than being silently absorbed.
--
-- Spend is AUD: the Schneider LinkedIn accounts carry the currency in the name suffix (_AUD today;
-- _USD@1.50 / _SGD@1.15 kept for robustness). LinkedIn has no currency column.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.stg_linkedin` AS
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
  FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
  WHERE ACCOUNT_NAME LIKE 'SchneiderElectric_TransmissionSG%'
)
SELECT
  DATE(DAY)                                AS metric_date,
  'linkedin'                               AS platform,
  campaign,
  CAMPAIGN_ID                              AS adset_id,
  CAMPAIGN_NAME                            AS adset_name,
  CAMPAIGN_GROUP_NAME                      AS group_name,
  CASE
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])NZ([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'New Zealand') THEN 'New Zealand'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'INDIA') THEN 'India'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(JP|JAPAN)([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Japan') THEN 'Japan'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'MEA') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(UAE|KSA)([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Saudi|Qatar|Egypt|Emirates)') THEN 'MEA'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SAM') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Brazil|Chile|Argentina|Mexico|Colombia|South America|LATAM)') THEN 'South America'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SEA') THEN 'SEA'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])ANZ([ _-]|$)') THEN 'ANZ'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Pacific') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])PAC([ _-]|$)') THEN 'Pacific'
    ELSE 'Unmapped'
  END                                      AS market,
  -- Creative: the ad TITLE is the message concept; CREATIVE_TYPE gives the format.
  COALESCE(NULLIF(TRIM(AD_TITLE), ''), 'Sponsored Content') AS concept,
  CASE
    WHEN CREATIVE_TYPE = 'STANDARD' THEN 'Single image'
    WHEN CREATIVE_TYPE IS NULL OR CREATIVE_TYPE = '' THEN 'Video / Other'
    ELSE CREATIVE_TYPE
  END                                      AS creative_format,
  COALESCE(NULLIF(TRIM(CREATIVE_NAME), ''), '(unnamed)') AS creative_name,
  IMPRESSIONS                              AS imps,
  CLICKS                                   AS clicks,
  CASE
    WHEN ENDS_WITH(ACCOUNT_NAME, '_USD') THEN COSTS * 1.50
    WHEN ENDS_WITH(ACCOUNT_NAME, '_SGD') THEN COSTS * 1.15
    ELSE COSTS
  END                                      AS spend_aud,
  -- LinkedIn's OWN on-platform lead-form counts. A PAID metric only: these are NOT Salesforce
  -- content-syndication leads and must never be summed into one. NULL on Trade Desk.
  LEADS                                    AS leads,
  LEAD_FORM_OPENS                          AS lead_form_opens
FROM scoped
WHERE campaign IS NOT NULL;
