-- cs_enriched_leads / cs_enriched_daily / cs_enriched_weekly: the "Weekly Enriched Leads" lane.
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
--       - '-'  : the bulk of rows (the one the request thread flagged).
--       - 'NA' : NOT flagged in the thread and easy to miss, because it survives every obvious
--                guard -- it is not NULL, not blank, not '-', and has a non-zero length.
--       - NULL / '' : zero rows today, handled anyway (a sentinel that is '-' now can become
--                NULL the day the upstream mapping changes).
--     A naive `WHERE ENRICHED_PHONE_NUMBER IS NOT NULL` counts EVERY lead as enriched and
--     reports 100% -- silently, in the flattering direction. Stopping at '-' alone is the more
--     dangerous near-miss: it looks right, reconciles against the thread's own ~74% figure, and
--     still overstates enrichment by 36% (495 vs the true 363 at 2026-09-07). It read
--     111/111 = 100% for w/c 31 Aug, a week that actually enriched 45 of 111 leads (40.5%).
--     So the test is: a value counts as enriched only if it is not a known sentinel AND CONTAINS
--     AT LEAST ONE DIGIT. The digit test is the backstop that makes the next unannounced
--     sentinel ('N/A', 'None', 'Unknown', a stray '--') fail CLOSED instead of inflating the
--     rate. Every real value is E.164-shaped (+61.../+91.../+65...); none is lost to it.
--
--     OPEN QUESTION with Transmission (raised 2026-09-07, Ankit + Fahad checking): the two
--     sentinels may not mean the same thing. 'NA' appears in the feed the same month enrichment
--     went live, and on the in-scope campaigns the '-' count falls to ZERO by w/c 31 Aug and
--     then springs back to 100% for the current part-week -- which reads like a PROCESSING
--     QUEUE ('-' = not yet attempted) rather than a result. If that is confirmed, the honest
--     denominator is 'NA' + real numbers (leads actually processed), not every lead, and the
--     rate roughly quadruples. NOTHING here assumes that yet: both are counted as "not
--     enriched", which is the conservative reading. Revisit when they come back.
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
-- THEATRE (added 2026-09-08, so the tab can render on the Core DG EMEA lane too) is resolved
-- from an EXPLICIT per-campaign list and can NEVER be defaulted -- the repo-wide rule after
-- sql/16 filed 64 EMEA leads under APJ on an `ELSE 'APAC'`. The scope is an INNER JOIN against
-- that list, so an unlisted campaign is excluded rather than mis-filed, and there is no ELSE
-- arm to get wrong.
--   - APJ  : the five ids Ian named. Deliberately a literal list -- it is a client-stated scope
--            ("these are the campaign IDs for now"), not a maintained dimension.
--   - EMEA : read from `seed_cs_emea_campaign_ids` (definitions.json -> definitions_seed.py),
--            which sql/16 and the theatre allowlist ALREADY use. Never re-type those ids here:
--            a second copy is how two surfaces start disagreeing about what EMEA is.
--
-- EMEA CARRIES ZERO ENRICHED NUMBERS TODAY (2,127 leads since 06 Aug, 1,438 of them 'NA', not
-- one real number). That is why the dashboard gates the tab on the theatre having at least one
-- enriched lead: publishing a 0% enrichment rate to the client would assert that enrichment is
-- failing for EMEA, when it may simply not be a service bought for that theatre. The tab lights
-- up on its own the day EMEA earns its first enriched number. Question is with Transmission.
--
-- Grain: cs_enriched_leads  = one row per LEAD (detail).
--        cs_enriched_daily  = DAY x THEATRE x MARKET x CAMPAIGN_ID (what the payload ships).
--        cs_enriched_weekly = ISO week x THEATRE x MARKET x CAMPAIGN_ID (SQL convenience + the
--                             job's reconciliation guard: daily must sum to weekly, per market).
--
-- WHY DAILY IS WHAT SHIPS: the tab is date-range driven (2026-09-08), and a range that cuts
-- mid-week CANNOT be honoured from week buckets -- the same reason sql/18_cs_compare_v2 is day
-- grain. The dashboard buckets days into ISO weeks itself, inside the selected range.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_leads` AS
WITH
-- APJ arm. Reads sql/10_salesforce_leads_live and joins back to the raw mirror ONLY for the
-- enriched-phone column, on LEAD_ID_SF. Verified clean: 2,285 Q3 rows in, 2,285 out, zero NULL
-- keys, zero duplicate keys in raw -- so the join cannot drop or double a lead.
--
-- WHY sql/10 AND NOT THE RAW TABLE (2026-09-10, the basis change). Four things this tab now
-- needs were each about to become a SECOND copy of a definition that already exists there:
--   LEAD_STATUS  -> the accepted bucket (the client's stated basis, below)
--   REGION_GRP   -> the market, which the CS tab's chips already show
--   PUBLISHER    -> the vendor
--   OFFER_TYPE   -> Pulse Survey / Qualification Questions / Precision MQL / Lead Magnet
-- Inheriting them means this tab cannot disagree with the CS tab about what a market is, which
-- leads are accepted, or which vendor sold one. It also brings sql/10's test-lead filter and its
-- quarter clamp for free, so the FIFTH copy of the Transmission predicate is GONE from the APJ
-- path rather than being kept in step by hand.
--   Cost of the move, stated so nobody reads it as a regression: sql/10 clamps DAY to the
--   quarter its campaign is named for and caps the 4 Q2-only campaigns, so the ALL-TIME figure
--   shifts slightly against the pre-2026-09-10 payload. Q3 is unaffected.
apj AS (
  SELECT
    l.DAY,
    l.CAMPAIGN,
    l.CAMPAIGN_ID,
    'APAC'                        AS THEATRE,
    l.PHONE,
    f.ENRICHED_PHONE_NUMBER       AS RAW_ENRICHED,
    l.LEAD_STATUS,
    l.REGION_GRP                  AS MARKET,
    l.PUBLISHER,
    l.OFFER_TYPE
  FROM `bidbrain-analytics.client_cloudflare.salesforce_leads_live` l
  JOIN `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all` f USING (LEAD_ID_SF)
),
-- EMEA arm. sql/10 is APAC-only (its 13-ID allowlist has never held an EMEA campaign), so this
-- side still reads raw, scoped by the maintained seed. MARKET / PUBLISHER / OFFER_TYPE are NULL,
-- never a placeholder string: EMEA's markets are the six campaign-name regions sql/16 carries,
-- and REGION_GRP's country lists are APAC-only, so resolving one here would file every EMEA lead
-- under OTHER and assert a judgement nobody made.
--   Transmission confirmed 2026-09-10 (Nabeel) that enrichment is APJ ONLY and EMEA is not
--   planned, so the tab's own gate -- render only where a theatre has an enriched lead -- is now
--   expected to keep EMEA dark indefinitely rather than temporarily.
emea AS (
  SELECT
    f.DAY,
    f.CAMPAIGN,
    f.CAMPAIGN_ID,
    'EMEA'                        AS THEATRE,
    f.PHONE,
    f.ENRICHED_PHONE_NUMBER       AS RAW_ENRICHED,
    f.LEAD_STATUS,
    CAST(NULL AS STRING)          AS MARKET,
    CAST(NULL AS STRING)          AS PUBLISHER,
    CAST(NULL AS STRING)          AS OFFER_TYPE
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all` f
  JOIN `bidbrain-analytics.client_cloudflare.seed_cs_emea_campaign_ids` s
    ON s.campaign_id = f.CAMPAIGN_ID
  -- Exclude Transmission TEST leads. The APJ arm inherits this from sql/10; this arm does not
  -- read sql/10, so it keeps its own copy -- character-for-character identical to the one in
  -- 10_salesforce_leads_live / 14_cf1_cs / 16_stg_cs_leads_v2. Match on the email DOMAIN, never
  -- the string 'test' (Advantest Corporation is a real lead) and never LIKE '%transmission%'
  -- (allisontransmission.com, dhoottransmission.com are real manufacturers).
  WHERE LOWER(IFNULL(SPLIT(f.EMAIL, '@')[SAFE_OFFSET(1)], '')) NOT IN
        ('transmissionagency.com', 'transmission.com')
),
both AS (SELECT * FROM apj UNION ALL SELECT * FROM emea)
SELECT
  DAY,
  CAMPAIGN,
  CAMPAIGN_ID,
  THEATRE,
  MARKET,
  PUBLISHER,
  OFFER_TYPE,
  PHONE,
  LEAD_STATUS,
  -- ACCEPTED is the client's stated basis for this tab (2026-09-10, Jade: "Enrichment % on this
  -- dashboard should be the total amount of leads accepted within that timeframe compared to the
  -- leads enriched and accepted"). Before this the tab counted DELIVERED, which is why its 1,030
  -- could not be reconciled against the CS tab's 1,868 and the client raised it.
  --
  -- THE THREE-STATUS SET IS A THIRD COPY. definitions.json `status_buckets.accepted` documents
  -- it, the dashboard hardcodes it as ACCEPTED_STATUSES, and it is written out here. All three
  -- must move together; it is a candidate for a seed table (see the client README).
  -- Replied/Unresponsive are both ZERO in Q3, so today the set is equivalent to 'Accepted'
  -- alone -- do NOT simplify it to that, or the tab silently diverges the first month one lands.
  LEAD_STATUS IN ('Accepted', 'Replied', 'Unresponsive') AS IS_ACCEPTED,
  -- The one normalisation. See header point 2. Order matters only for legibility; the digit
  -- test alone would catch '-' and 'NA' today, but the explicit list DOCUMENTS the two sentinels
  -- actually observed in the feed, and stays correct if a future sentinel contains a digit
  -- (a '0', a '000'), which the digit test would wave through.
  CASE
    WHEN TRIM(IFNULL(RAW_ENRICHED, '')) = ''                                  THEN NULL
    WHEN UPPER(TRIM(RAW_ENRICHED)) IN
         ('-', '--', 'NA', 'N/A', 'N.A.', 'NONE', 'NULL', 'UNKNOWN', 'NIL')   THEN NULL
    WHEN NOT REGEXP_CONTAINS(RAW_ENRICHED, r'[0-9]')                          THEN NULL
    ELSE TRIM(RAW_ENRICHED)
  END AS ENRICHED_PHONE,
  -- Carried so the open '-' vs 'NA' question can be answered from the dashboard without a schema
  -- change. NOT surfaced to the client yet. Transmission told us (2026-09-10, Nabeel) the field
  -- is "either a phone number or NA, there is no blank field" -- MEASURABLY NOT TRUE: '-' sits
  -- on 306 of VRSM's 466 accepted Q3 leads and on 7 of Final Funnel Qualification Questions'.
  -- Back with Nabeel; until it is answered BOTH sentinels stay "not enriched", the conservative
  -- read, and nothing on screen assumes otherwise.
  CASE
    WHEN UPPER(TRIM(IFNULL(RAW_ENRICHED, ''))) = 'NA' THEN 'NA'
    WHEN TRIM(IFNULL(RAW_ENRICHED, '')) = '-'         THEN 'DASH'
    WHEN REGEXP_CONTAINS(IFNULL(RAW_ENRICHED, ''), r'[0-9]') THEN 'VALUE'
    ELSE 'OTHER'
  END AS ENRICHED_STATE
FROM both;


-- DAY grain: what the payload ships, so a mid-week date range is exact. See header.
--
-- OFFER_TYPE IS IN THE GRAIN so the BENCHMARK is derivable in the browser without another SQL
-- change. The client's target is "ALL leads with pulse survey and qualification questions"
-- (2026-09-10) = every accepted lead on those offers should carry an enriched number. Whether
-- VRSM's Lead Magnet joins that set is OPEN with the client (Transmission say it IS enriched;
-- 361 accepted vs 827, 81% vs 41%), so the target is a FRONTEND set over this column and never
-- a hardcoded number here -- switching it is one constant, not a redeploy of the view.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_daily` AS
SELECT
  DAY,
  THEATRE,
  MARKET,
  PUBLISHER,
  OFFER_TYPE,
  CAMPAIGN_ID,
  -- One CAMPAIGN string per id, so the id can be labelled without a second join. MIN(), not
  -- ANY_VALUE(): a deterministic spelling, so the label cannot flicker between runs.
  MIN(CAMPAIGN)                                          AS CAMPAIGN,
  -- BOTH bases are carried. ACCEPTED_* is what the tab renders from 2026-09-10; the delivered
  -- counts stay so a delivery figure is still available and so the job can assert one against
  -- the other. A consumer must never MIX them -- that is the near-miss basis error the CS
  -- by-market chart shipped with (md/AGENTS.md, "pace in the unit the plan is bought in").
  COUNT(*)                                               AS LEAD_COUNT,
  COUNTIF(IS_ACCEPTED)                                   AS ACCEPTED_COUNT,
  COUNTIF(ENRICHED_PHONE IS NOT NULL)                    AS ENRICHED_COUNT,
  COUNTIF(IS_ACCEPTED AND ENRICHED_PHONE IS NOT NULL)    AS ACCEPTED_ENRICHED_COUNT,
  -- The '-' vs 'NA' split, on the ACCEPTED basis to match everything above it. Internal.
  COUNTIF(IS_ACCEPTED AND ENRICHED_STATE = 'DASH')       AS DASH_COUNT,
  COUNTIF(IS_ACCEPTED AND ENRICHED_STATE = 'NA')         AS NA_COUNT
FROM `client_cloudflare.cs_enriched_leads`
GROUP BY DAY, THEATRE, MARKET, PUBLISHER, OFFER_TYPE, CAMPAIGN_ID;


-- ISO week rollup, so WEEK_START is always a Monday and lines up with the Monday anchor every
-- other CS weekly surface on this dashboard uses (sql/17_cs_pacing_v2). Kept as the SQL-level
-- convenience AND as the job's reconciliation guard: cs_enriched_daily must sum to this exactly.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_weekly` AS
SELECT
  DATE_TRUNC(DAY, ISOWEEK)                               AS WEEK_START,
  THEATRE,
  MARKET,
  PUBLISHER,
  OFFER_TYPE,
  CAMPAIGN_ID,
  MIN(CAMPAIGN)                                          AS CAMPAIGN,
  COUNT(*)                                               AS LEAD_COUNT,
  COUNTIF(IS_ACCEPTED)                                   AS ACCEPTED_COUNT,
  COUNTIF(ENRICHED_PHONE IS NOT NULL)                    AS ENRICHED_COUNT,
  COUNTIF(IS_ACCEPTED AND ENRICHED_PHONE IS NOT NULL)    AS ACCEPTED_ENRICHED_COUNT,
  -- The rate at THIS grain, on the ACCEPTED basis. SAFE_DIVIDE, so a week with no accepted lead
  -- is NULL, never a divide-by-zero. Anything aggregating across campaigns MUST re-derive the
  -- rate from the two summed counts and never average these -- a rate is not additive.
  SAFE_DIVIDE(COUNTIF(IS_ACCEPTED AND ENRICHED_PHONE IS NOT NULL),
              COUNTIF(IS_ACCEPTED))                      AS ENRICHMENT_RATE
FROM `client_cloudflare.cs_enriched_leads`
GROUP BY WEEK_START, THEATRE, MARKET, PUBLISHER, OFFER_TYPE, CAMPAIGN_ID;
