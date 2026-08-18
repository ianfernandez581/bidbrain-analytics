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
-- ...BUT A COARSE TOKEN LEFT BY A MID-FLIGHT RENAME IS NOT A THIRD MARKET (2026-08-18, client).
-- Industrial Edge showed Australia, New Zealand *and* ANZ. It never ran a combined-ANZ line:
-- Transmission renamed five ad sets from `SE_Industrial Edge_<Phase>_{AU,NZ}` to
-- `2463_..._<PH>_ANZ_<fmt>` on 2026-08-07 and back to the per-country form on 08-13, so six days of
-- each ad set's delivery (5,619 imps / A$855) parsed as a phantom 'ANZ' market and drew a third
-- market chip, a third table row and a third stacked series. The ad set ID never moved.
-- So: when a row's OWN name resolves to a coarse token but that ad set's CURRENT name (the most
-- recent day it delivered) names a specific country, the row takes the ad set's current country.
-- Deliberately narrow, in both directions:
--   * a row whose own name already names a country is NEVER rewritten — real per-country history is
--     not retro-relabelled if an ad set genuinely changes geo later;
--   * an ad set that is STILL named with a coarse token keeps it (Enterprise IT's `_PAC_` ad sets
--     stay 'Pacific'), so a genuine combined-market line is not invented into a country it never had.
-- Same principle 05_linkedin_adsets already applies to the ad-set name: the ad set is the key, the
-- name is not (md/AGENTS.md). Verified a strict no-op on ent_it and software_first — it moves
-- exactly the six ind_edge rows.
--
-- TACTIC is the media-plan LINE ITEM (funnel stage). The 2463 plan buys Awareness / Consideration /
-- Conversion lines but the dashboard reported CHANNEL only, so a line-item view was impossible
-- (client, 2026-08-18). Parsed from the ad-set name, most-specific token first: Retargeting before
-- Conversion before Consideration before Awareness, because 'CONVERSION' CONTAINS 'CON' — a
-- Consideration-first ladder mislabels every conversion ad set. Short tokens are delimiter-anchored
-- so 'CON' cannot match inside a word, and the retargeting arm accepts the numbered forms
-- (RTG / RTG1 / RT1) Transmission actually uses — the plain `RTG|RT1|RT2` set this replaced could not
-- match `..._RTG1_ANZ_image` at all, because the digit sits between RTG and the delimiter.
-- Enterprise IT's ad sets carry a VERTICAL (Hero / Generic / Manufacturing / ...) rather than a
-- funnel stage, so they land on 'Unspecified' by design — that is true of the brief, not a parse
-- failure. This column is the SINGLE definition of the funnel stage: 05_linkedin_adsets reads its
-- `phase` from here rather than re-deriving the same ladder.
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
),
parsed AS (
  SELECT
    DATE(DAY)                                AS metric_date,
    campaign,
    CAMPAIGN_ID                              AS adset_id,
    CAMPAIGN_NAME                            AS adset_name,
    CAMPAIGN_GROUP_NAME                      AS group_name,
    -- The market THIS row's own name reads. Reconciled against the ad set's current name below.
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
    END                                      AS market_raw,
    -- Media-plan LINE ITEM (funnel stage). Most-specific token first - see the header.
    CASE
      WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(RTG[0-9]*|RT[0-9])([ _-]|$)')
        OR CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'RETARGET')            THEN 'Retargeting'
      WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])CNV([ _-]|$)')
        OR CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'CONVERSION')          THEN 'Conversion'
      WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(CNS|CON)([ _-]|$)')
        OR CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'CONSIDERATION')       THEN 'Consideration'
      WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AWR([ _-]|$)')
        OR CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'AWARENESS')           THEN 'Awareness'
      ELSE 'Unspecified'
    END                                      AS tactic,
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
  WHERE campaign IS NOT NULL
),
resolved AS (
  SELECT
    p.*,
    -- The market this ad set's CURRENT name resolves to - i.e. the most recent day it delivered.
    -- Partitioned on the ID (the stable key); the name is only a fallback so that a NULL id from the
    -- mirror could never pool every id-less ad set into one group.
    FIRST_VALUE(market_raw) OVER (
      PARTITION BY COALESCE(CAST(adset_id AS STRING), adset_name)
      ORDER BY metric_date DESC, imps DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
    )                                        AS market_now
  FROM parsed p
)
SELECT
  metric_date,
  'linkedin'                                 AS platform,
  campaign,
  adset_id,
  adset_name,
  group_name,
  -- A row keeps its own country; only a coarse / unparsed token defers to the ad set's current one.
  CASE
    WHEN market_raw IN ('Australia','New Zealand','India','Japan','MEA','South America','SEA') THEN market_raw
    WHEN market_now IN ('Australia','New Zealand','India','Japan','MEA','South America','SEA') THEN market_now
    ELSE market_raw
  END                                        AS market,
  tactic,
  concept,
  creative_format,
  creative_name,
  imps,
  clicks,
  spend_aud,
  leads,
  lead_form_opens
FROM resolved;
