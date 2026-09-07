-- cs_enriched_leads / cs_enriched_weekly: the "Weekly Enriched Leads" lane.
--
-- Client request (2026-09-07, Ian -> Transmission): show how many CS leads arrive with an
-- ENRICHED phone number on top of the PHONE every lead already carries, weekly, for the five
-- campaigns below. Transmission added ENRICHED_PHONE_NUMBER to the Salesforce sync and it has
-- landed in the shared mirror (verified 2026-09-07: 29 columns, PHONE + ENRICHED_PHONE_NUMBER).
--
-- FOUR facts about this column, all verified against the mirror -- do not re-derive them:
--
--  1. It is named ENRICHED_PHONE_NUMBER (uppercase, TEXT). The request thread calls it
--     "EnrichedPhoneNumber"; that spelling exists NOWHERE in the mirror. Key off the real name.
--
--  2. IT HAS TWO "EMPTY" SENTINELS, NEITHER OF THEM NULL: a literal dash '-' AND the literal
--     string 'NA'. This is the whole trap in this view.
--       - '-'  : 1,427 of 1,923 in-scope leads (the one the request thread flagged).
--       - 'NA' : 132 more. NOT flagged in the thread and easy to miss, because it survives every
--                obvious guard -- it is not NULL, not blank, not '-', and has a non-zero length.
--       - NULL / '' : zero rows today, handled anyway (a sentinel that is '-' now can become
--                NULL the day the upstream mapping changes).
--     A naive `WHERE ENRICHED_PHONE_NUMBER IS NOT NULL` counts EVERY lead as enriched and
--     reports 100% -- silently, in the flattering direction. Stopping at '-' alone is the more
--     dangerous near-miss: it looks right, reconciles against the thread's own ~74% figure, and
--     still overstates enrichment by 36% (495 vs the true 363). It read 111/111 = 100% for
--     w/c 31 Aug, a week that actually enriched 45 of 111 leads (40.5%).
--     So the test is: a value counts as enriched only if it is not a known sentinel AND CONTAINS
--     AT LEAST ONE DIGIT. The digit test is the backstop that makes the next unannounced
--     sentinel ('N/A', 'None', 'Unknown', a stray '--') fail CLOSED instead of inflating the
--     rate. All 363 real values are E.164-shaped (+61.../+91.../+65...); none is lost to it.
--
--  3. Weekly bucketing is off DAY (a DATE, the true per-lead delivery date). NOT DT_CREATED,
--     which is the Snowflake bulk-load instant and stamps every row identically -- bucketing on
--     it collapses the whole flight into one week. Same trap already documented in sql/14_cf1_cs.
--
--  4. PHONE is 100% populated in scope, so it is the fallback/reference column and never needs
--     a COALESCE against the enriched one.
--
-- NORMALISED ONCE, HERE. `ENRICHED_PHONE` is NULL for every sentinel and for anything carrying
-- no digit, else the trimmed value -- so nothing downstream repeats the test. The job and the
-- dashboard do a plain IS NOT NULL / != null and cannot get it wrong; adding a third sentinel is
-- then a one-line change in this file rather than a hunt through three layers.
--
-- Grain: cs_enriched_leads = one row per LEAD (detail). cs_enriched_weekly = one row per
-- (WEEK_START, CAMPAIGN_ID) so campaign stays available as a dimension.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_leads` AS
SELECT
  DAY,
  CAMPAIGN,
  CAMPAIGN_ID,
  PHONE,
  -- The one normalisation. See header point 2. Order matters only for legibility; the digit
  -- test alone would catch '-' and 'NA' today, but the explicit list DOCUMENTS the two sentinels
  -- actually observed in the feed, and stays correct if a future sentinel contains a digit
  -- (a '0', a '000'), which the digit test would wave through.
  CASE
    WHEN TRIM(IFNULL(ENRICHED_PHONE_NUMBER, '')) = ''                       THEN NULL
    WHEN UPPER(TRIM(ENRICHED_PHONE_NUMBER)) IN
         ('-', '--', 'NA', 'N/A', 'N.A.', 'NONE', 'NULL', 'UNKNOWN', 'NIL') THEN NULL
    WHEN NOT REGEXP_CONTAINS(ENRICHED_PHONE_NUMBER, r'[0-9]')               THEN NULL
    ELSE TRIM(ENRICHED_PHONE_NUMBER)
  END AS ENRICHED_PHONE
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
-- Scope: the five campaign IDs the client named. Deliberately an EXPLICIT id list and not a
-- CAMPAIGN-name match -- these names are the `2026_Q2_...` / `2026_Q3_...` convention that the
-- repo-wide "campaign names are NOT stable keys" rule warns about (two of the five share a
-- byte-identical CAMPAIGN string and are told apart ONLY by id). A sixth campaign is a row here.
WHERE CAMPAIGN_ID IN (
    '701RG00001ElTu3YAF',
    '701RG00001ElVXdYAN',
    '701RG00001ElUa0YAF',
    '701RG00001ElNYkYAN',
    '701RG00001W1FQRYA3'
  )
  -- Exclude Transmission TEST leads. IDENTICAL predicate to 10_salesforce_leads_live,
  -- 14_cf1_cs and 16_stg_cs_leads_v2 -- keep all four character-for-character the same. This is
  -- NOT a no-op here: 9 of the 1,932 in-scope leads are test leads (2026-09-07), so without it
  -- this panel would report 9 more leads for the same period than every other CS figure on the
  -- same dashboard, which is exactly how the APJ KPI strip and Pacing detail came to disagree.
  --
  -- Match on the email DOMAIN, never on the string 'test' anywhere: a real rejected lead from
  -- Advantest Corporation (advantest.com) carries 'test' in its name and domain. And match the
  -- domain EXACTLY, never LIKE '%transmission%', which would drop allisontransmission.com and
  -- dhoottransmission.com -- real manufacturers.
  AND LOWER(IFNULL(SPLIT(EMAIL, '@')[SAFE_OFFSET(1)], '')) NOT IN
      ('transmissionagency.com', 'transmission.com');


-- Weekly rollup. ISOWEEK, so WEEK_START is always a Monday and lines up with the Monday anchor
-- every other CS weekly surface on this dashboard uses (sql/17_cs_pacing_v2).
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_weekly` AS
SELECT
  DATE_TRUNC(DAY, ISOWEEK)                        AS WEEK_START,
  CAMPAIGN_ID,
  -- One CAMPAIGN string per id, so the id can be labelled without a second join. MIN(), not
  -- ANY_VALUE(): a deterministic spelling, so the label cannot flicker between runs.
  MIN(CAMPAIGN)                                   AS CAMPAIGN,
  COUNT(*)                                        AS LEAD_COUNT,
  COUNTIF(ENRICHED_PHONE IS NOT NULL)             AS ENRICHED_COUNT,
  -- The rate at THIS grain (week x campaign). SAFE_DIVIDE, so an empty week is NULL, never a
  -- divide-by-zero. Anything aggregating across campaigns MUST re-derive the rate from the two
  -- summed counts and never average these -- a rate is not additive (repo-wide rule).
  SAFE_DIVIDE(COUNTIF(ENRICHED_PHONE IS NOT NULL), COUNT(*)) AS ENRICHMENT_RATE
FROM `client_cloudflare.cs_enriched_leads`
GROUP BY WEEK_START, CAMPAIGN_ID;
