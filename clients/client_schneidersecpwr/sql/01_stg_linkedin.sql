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
-- CAMPAIGN NAME WINS; THE CAMPAIGN GROUP IS A FALLBACK, NOT A CO-EQUAL (2026-09-02).
-- LinkedIn's group names are mislabelled here in BOTH directions: a group named
-- `2305_SE_ANZ Industrial Edge W3 Prefab` holds campaigns named `2463_SE_Industrial Edge Wave3_*`,
-- and a group named `2463_SE_Software First EcoStruxure_AWR_ANZ_static` holds campaigns named
-- `2305_SE Software First EcoStruxure - AWR AU`. So the group may NEVER overrule a name that
-- already carries a brief token - doing that is what would cross-tag two briefs.
--
-- But matching on the name ALONE silently dropped a live brief-2305 line. Transmission's A/B test
-- `2305_Software First_A/B test (Expert Webpage vs Interactive Demo Page) Test` (LinkedIn campaign
-- group 1191212126, live 2026-08-20) names its two ad sets `ANZ Ad Set A - Expert Page` and
-- `ANZ Ad Set B - Interactive Demo`. Those carry NO brief number, NO `Software First` and NO
-- `EcoStruxureIT` - the brief is stated ONLY on the group - so 1,333 imps / 5 clicks / A$1,633.56 of
-- real delivery reached no KPI, table, chart, CSV or deck. Silent, because a row rejected here never
-- reaches the market or tactic parsers either, so no 'Unmapped' chip could flag it.
-- No name token could have caught these without being recklessly generic (`ANZ Ad Set` would claim
-- any future brief that happens to name an ad set that way).
--
-- Hence the two tiers below, in this order and no other:
--   TIER 1  the campaign's OWN name. Authoritative, and unchanged from the original predicate.
--   TIER 2  the campaign GROUP's name, consulted ONLY when tier 1 resolves to NULL.
-- A row that already names a brief is therefore never re-tagged by its group (the two mislabelled
-- groups above still resolve by name), and a row whose name is silent about the brief is read from
-- the only place that states it. Repo rule (md/AGENTS.md): "prefer the predicate that lets a
-- stranger in over the one that quietly drops a client" - under-inclusion is silent here, whereas an
-- over-inclusion lands in a NAMED brief and shows up as delivery someone can see and query.
--
-- VERIFIED BY WHAT IT ADMITS, not by a before/after total (md/AGENTS.md: "a scope fix meant to admit
-- rows must be verified by what it admits" - a no-op check is the WRONG test for a widening). Across
-- every `SchneiderElectric_TransmissionSG%` row, the group fallback admits EXACTLY the two A/B ad
-- sets above and nothing else: every other campaign in the account either already resolves by name,
-- or has a group name that matches no token either. Re-run that enumeration before widening a token
-- again.
--
-- Note the A/B ad sets legitimately read market 'ANZ' and tactic 'Unspecified'. They are a genuine
-- combined-ANZ line - never named per-country, so the coarse-token reconciliation below correctly
-- leaves them alone, and they are NOT the phantom ANZ a rename artefact created on ind_edge - and
-- their names carry no funnel-stage token. Both are true of the buy, not parse failures.
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
    COALESCE(
      -- TIER 1 - the campaign's OWN name. Authoritative: it wins wherever it resolves, so a
      -- mislabelled campaign GROUP can never re-tag a campaign that states its own brief.
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
      END,
      -- TIER 2 - the campaign GROUP's name, reached ONLY when tier 1 is silent. Same token sets,
      -- deliberately: a brief is a brief wherever it is written. This is what admits the 2305 A/B
      -- test, whose ad-set names carry no brief token at all.
      CASE
        WHEN CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'EntIT') THEN 'ent_it'
        WHEN CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'SE_Industrial Edge_')
          OR CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'Industrial Edge Wave3')
          OR CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'Industrial Edge W3')
          OR STARTS_WITH(TRIM(CAMPAIGN_GROUP_NAME), '2463_') THEN 'ind_edge'
        WHEN CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'Software First')
          OR CONTAINS_SUBSTR(CAMPAIGN_GROUP_NAME, 'EcoStruxureIT')
          OR STARTS_WITH(TRIM(CAMPAIGN_GROUP_NAME), '2305_') THEN 'software_first'
        ELSE NULL
      END
    ) AS campaign
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
