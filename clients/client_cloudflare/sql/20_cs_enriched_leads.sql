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
WITH scope AS (
  -- EMEA: the maintained list, never re-typed. See header.
  SELECT campaign_id AS CAMPAIGN_ID, 'EMEA' AS THEATRE
  FROM `bidbrain-analytics.client_cloudflare.seed_cs_emea_campaign_ids`
  UNION ALL
  -- APJ: the client-stated scope. A sixth campaign is one row here.
  SELECT id, 'APAC'
  FROM UNNEST([
    '701RG00001ElTu3YAF',
    '701RG00001ElVXdYAN',
    '701RG00001ElUa0YAF',
    '701RG00001ElNYkYAN',
    '701RG00001W1FQRYA3'
  ]) AS id
)
SELECT
  f.DAY,
  f.CAMPAIGN,
  f.CAMPAIGN_ID,
  s.THEATRE,
  f.PHONE,
  -- The one normalisation. See header point 2. Order matters only for legibility; the digit
  -- test alone would catch '-' and 'NA' today, but the explicit list DOCUMENTS the two sentinels
  -- actually observed in the feed, and stays correct if a future sentinel contains a digit
  -- (a '0', a '000'), which the digit test would wave through.
  CASE
    WHEN TRIM(IFNULL(f.ENRICHED_PHONE_NUMBER, '')) = ''                       THEN NULL
    WHEN UPPER(TRIM(f.ENRICHED_PHONE_NUMBER)) IN
         ('-', '--', 'NA', 'N/A', 'N.A.', 'NONE', 'NULL', 'UNKNOWN', 'NIL')   THEN NULL
    WHEN NOT REGEXP_CONTAINS(f.ENRICHED_PHONE_NUMBER, r'[0-9]')               THEN NULL
    ELSE TRIM(f.ENRICHED_PHONE_NUMBER)
  END AS ENRICHED_PHONE,
  -- Carried so the open '-' vs 'NA' question above can be answered from the dashboard without a
  -- schema change the day Transmission confirms what they mean. NOT surfaced to the client yet.
  CASE
    WHEN UPPER(TRIM(IFNULL(f.ENRICHED_PHONE_NUMBER, ''))) = 'NA' THEN 'NA'
    WHEN TRIM(IFNULL(f.ENRICHED_PHONE_NUMBER, '')) = '-'         THEN 'DASH'
    WHEN REGEXP_CONTAINS(IFNULL(f.ENRICHED_PHONE_NUMBER, ''), r'[0-9]') THEN 'VALUE'
    ELSE 'OTHER'
  END AS ENRICHED_STATE,
  -- MARKET (2026-09-10, client request via Jade: "can you do a market breakdown of the
  -- enrichment %"). Resolved from COUNTRY_NAME -- the LEAD's own country -- which is the
  -- definition sql/10_salesforce_leads_live uses for REGION_GRP and therefore what the CS
  -- tab's market chips already show. Keep the country lists character-for-character the same
  -- as sql/10's; two market definitions on one dashboard is how two panels start disagreeing.
  --
  -- DELIBERATELY NOT sql/16_stg_cs_leads_v2's MARKET, for two reasons that are easy to miss:
  --   1. Its SEG_REGION is SPLIT(CAMPAIGN,'_')[SAFE_OFFSET(2)] -- parsed from the CAMPAIGN
  --      NAME, so it is a property of the campaign, not the lead. Across a 5-campaign scope
  --      that is close to a relabelling of the campaign picker already on this tab, and it is
  --      not what "market" means to the client.
  --   2. That view's base CTE is scoped STARTS_WITH(CAMPAIGN,'2026_Q3'), and this lane runs
  --      from 2026-03-27. It could not resolve a market for the pre-Q3 half of these leads.
  --
  -- RIG IS CARRIED, and evaluated BEFORE geography exactly as sql/10 does. It was left out of
  -- the first cut on the reasoning that RIG is Q3-hidden estate-wide (2026-08-05) and this tab
  -- defaults to the current quarter -- but that made this column sql/10's definition MINUS an
  -- arm, so at any range reaching before Q3 the same lead would read RIG on the CS tab and a
  -- geographic market here, on one dashboard. Measured: 0 RIG-asset leads in scope for Q3, 64
  -- pre-Q3. Carrying the arm costs nothing in the default view (no rows -> no chip, no table
  -- row, so it self-hides) and removes the divergence outright.
  --
  -- KR stays campaign-scoped off the SAME seed sql/10 reads, not re-typed. All five in-scope
  -- campaigns are in that seed today, so it is currently a no-op -- it is here so the two
  -- definitions cannot drift if the enrichment scope grows.
  --
  -- 'OTHER' is a REAL row, not a residual to drop: the market rows must sum to the headline
  -- "Leads in scope" or the two disagree the day an unmapped country arrives. Empty today
  -- (all 1,030 Q3 leads resolve), which is exactly why it would be easy to leave out.
  --
  -- APAC ONLY, AND THE THEATRE GATE IS LOAD-BEARING. sql/10's country lists cover the APAC
  -- markets and nothing else, so without this gate all 2,634 EMEA leads resolve to 'OTHER' -
  -- caught by the export job's guard on the first run of this column. EMEA is NULL, not
  -- 'OTHER': 'OTHER' asserts "we looked and this country is outside the plan", NULL says
  -- "no resolver for this theatre yet", and only the second is true. The dashboard hides the
  -- whole market card when a theatre resolves no markets, so the EMEA tab cannot render a
  -- breakdown of one meaningless bucket.
  --
  -- GIVING EMEA REAL MARKETS IS NOT A COUNTRY-LIST EXTENSION. Every other EMEA panel on this
  -- dashboard splits by the SIX campaign-name markets (UKI/DACH/SEUR/NEUR/CEERI/MEA) that
  -- sql/16 resolves, because that is the grain the EMEA targets are bought at. Writing a
  -- COUNTRY_NAME -> EMEA-region map here would be a second, disagreeing definition of a
  -- dimension the campaign name already carries - the exact thing sql/16's header warns about.
  -- The EMEA enriched tab is hidden today (zero enriched leads across 2,634), so this is not
  -- blocking; do it properly on the day that tab lights up.
  CASE
    WHEN s.THEATRE <> 'APAC' THEN NULL
    -- RIG: asset-based, so it is evaluated BEFORE geography and deliberately pulls its leads
    -- out of every geographic market (the overlap is intentional). Same seeds sql/10 reads.
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) <> 'KOREA, REPUBLIC OF'
         AND f.ASSET_2 IN (SELECT asset_2
                           FROM `bidbrain-analytics.client_cloudflare.seed_rig_assets`)
         AND f.CAMPAIGN_ID IN (SELECT campaign_id
                               FROM `bidbrain-analytics.client_cloudflare.seed_rig_campaign_ids`)
                                                                                       THEN 'RIG'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) = 'KOREA, REPUBLIC OF'
         AND f.CAMPAIGN_ID IN (SELECT campaign_id
                               FROM `bidbrain-analytics.client_cloudflare.seed_kr_campaign_ids`)
                                                                                       THEN 'KR'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) IN ('AUSTRALIA', 'NEW ZEALAND')                    THEN 'ANZ'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) IN ('SINGAPORE', 'MALAYSIA', 'INDONESIA',
                                         'THAILAND', 'VIET NAM', 'VIETNAM',
                                         'PHILIPPINES')                                THEN 'ASEAN'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) = 'INDIA'                                         THEN 'SAARC'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) IN ('CHINA', 'MAINLAND CHINA', 'TAIWAN',
                                         'HONG KONG')                                  THEN 'GCR'
    WHEN UPPER(TRIM(f.COUNTRY_NAME)) = 'JAPAN'                                         THEN 'JP'
    ELSE 'OTHER'
  END AS MARKET
FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all` f
-- INNER JOIN = the scope gate AND the theatre resolver in one step. An unlisted campaign is
-- dropped, never defaulted onto a theatre.
JOIN scope s USING (CAMPAIGN_ID)
-- Exclude Transmission TEST leads. IDENTICAL predicate to 10_salesforce_leads_live,
-- 14_cf1_cs and 16_stg_cs_leads_v2 -- keep all four character-for-character the same. This is
-- NOT a no-op here: 9 of the in-scope leads are test leads (2026-09-07), so without it this
-- panel would report 9 more leads for the same period than every other CS figure on the
-- same dashboard, which is exactly how the APJ KPI strip and Pacing detail came to disagree.
--
-- Match on the email DOMAIN, never on the string 'test' anywhere: a real rejected lead from
-- Advantest Corporation (advantest.com) carries 'test' in its name and domain. And match the
-- domain EXACTLY, never LIKE '%transmission%', which would drop allisontransmission.com and
-- dhoottransmission.com -- real manufacturers.
WHERE LOWER(IFNULL(SPLIT(f.EMAIL, '@')[SAFE_OFFSET(1)], '')) NOT IN
      ('transmissionagency.com', 'transmission.com');


-- DAY grain: what the payload ships, so a mid-week date range is exact. See header.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_daily` AS
SELECT
  DAY,
  THEATRE,
  MARKET,
  CAMPAIGN_ID,
  -- One CAMPAIGN string per id, so the id can be labelled without a second join. MIN(), not
  -- ANY_VALUE(): a deterministic spelling, so the label cannot flicker between runs.
  MIN(CAMPAIGN)                        AS CAMPAIGN,
  COUNT(*)                             AS LEAD_COUNT,
  COUNTIF(ENRICHED_PHONE IS NOT NULL)  AS ENRICHED_COUNT,
  -- The '-' vs 'NA' split, for the open question with Transmission. Internal for now.
  COUNTIF(ENRICHED_STATE = 'DASH')     AS DASH_COUNT,
  COUNTIF(ENRICHED_STATE = 'NA')       AS NA_COUNT
FROM `client_cloudflare.cs_enriched_leads`
GROUP BY DAY, THEATRE, MARKET, CAMPAIGN_ID;


-- ISO week rollup, so WEEK_START is always a Monday and lines up with the Monday anchor every
-- other CS weekly surface on this dashboard uses (sql/17_cs_pacing_v2). Kept as the SQL-level
-- convenience AND as the job's reconciliation guard: cs_enriched_daily must sum to this exactly.
CREATE OR REPLACE VIEW `client_cloudflare.cs_enriched_weekly` AS
SELECT
  DATE_TRUNC(DAY, ISOWEEK)                        AS WEEK_START,
  THEATRE,
  MARKET,
  CAMPAIGN_ID,
  MIN(CAMPAIGN)                                   AS CAMPAIGN,
  COUNT(*)                                        AS LEAD_COUNT,
  COUNTIF(ENRICHED_PHONE IS NOT NULL)             AS ENRICHED_COUNT,
  -- The rate at THIS grain (week x theatre x market x campaign). SAFE_DIVIDE, so an empty
  -- week is NULL,
  -- never a divide-by-zero. Anything aggregating across campaigns MUST re-derive the rate from
  -- the two summed counts and never average these -- a rate is not additive (repo-wide rule).
  SAFE_DIVIDE(COUNTIF(ENRICHED_PHONE IS NOT NULL), COUNT(*)) AS ENRICHMENT_RATE
FROM `client_cloudflare.cs_enriched_leads`
GROUP BY WEEK_START, THEATRE, MARKET, CAMPAIGN_ID;
