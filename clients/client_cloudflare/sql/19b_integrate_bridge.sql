-- 19b_integrate_bridge.sql
--
-- THE ONE PLACE INTEGRATE'S LEAD RECORD IS READ. Everything else reads THIS view.
--
-- `raw_snowflake.integrate_leads` carries first/last name, email, phone, street and postcode on
-- every row (43 columns, mirrored whole because the loader is SELECT *). This view is the
-- membrane: it emits a HASHED key, the campaign, the source id, the disposition and a scrubbed
-- reason - and nothing else. No consumer may reference the raw table.
--
-- IT ANSWERS EXACTLY TWO QUESTIONS, and deliberately not a third:
--   1. WHICH OFFER did this lead come from?   (sql/23 - the enrichment-by-publisher lane)
--   2. WHY was it rejected?                    (sql/22 - the rejection-reason panel)
--   3. WAS it enriched?                        (sql/20 - a BLANK-FILL, never a replacement)
--
-- NUMBERED 19b, NOT 21, PURELY FOR APPLY ORDER: sql/20 reads it, and create_views.py applies
-- files in sorted filename order, so a `21_` bridge would not exist yet when sql/20 is built.
-- It does NOT supply enrichment counts. Integrate holds 56 enrichments for VRSM that Salesforce
-- does not, and Salesforce holds 36 (the 2026-07-21 Precision MQL batch) that Integrate does
-- not, so the two disagree in BOTH directions. Counting enrichment from here would put a second
-- enrichment figure on the same screen as the existing Weekly Enriched Leads tab and let the
-- two contradict - the exact defect the client raised on the pacing card on 2026-09-16.
-- SALESFORCE REMAINS THE SOLE SOURCE OF ENRICHMENT COUNTS. Integrate supplies the SPLIT only.
--
-- THE OFFER COMES FROM `URL`, and this is the find that unblocked the VRSM split. Integrate has
-- no offer column, `QUESTION_1` is near-unique free text (106 distinct values over 156 rows) and
-- ASSET_TITLE is reused across offers (94% of leads sit on an asset used by both), so neither
-- can separate them. The landing-page path can: it ends `-pulse-survey` or
-- `-qualification-que`. Measured on VRSM Q3 - 79 Pulse / 74 Qualification / 471 Lead Magnet,
-- agreeing with question-presence on 619 of 624 rows (99.2%), and corroborated independently by
-- enrichment outcome (82% of the two survey offers carry a real number, against 0.6% of Lead
-- Magnet). It is a URL CONVENTION, not a declared field, so it is confined to the one campaign
-- that needs it - see sql/23 - and it must be confirmed with Transmission before any figure
-- derived from it is described to the client as their own definition.
--
-- ONE ROW PER (lead, campaign). Fan-out tie-break is latest UPDATED_TIMESTAMP, then
-- DISPOSITION_CODE alphabetically so two runs can never disagree. Measured 2026-09-18: 24
-- fan-out groups, 18 agreeing on the code, and all 6 disagreements are ACCEPTED leads moving
-- POSTOUT_SUCCESS -> MQL_MARKET_QUALIFIED_LEAD, so no rejected lead is affected today.
--
-- DATES ARE TEXT UPSTREAM ('MM/DD/YYYY HH24:MI:SS') and every column in the source is TEXT,
-- including CPL. Parse with SAFE.PARSE_TIMESTAMP - a format change upstream must degrade to
-- NULL and lose the tie-break ordering, never fail the whole view.

CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.integrate_bridge` AS
WITH source_map AS (
  -- The "Integrate Source Details" dictionary (Nabeel, 2026-09-18). Carries BOTH spellings:
  -- 3 of the 11 differ from ours (VSRM / SitPub / Inbox Insights), and nothing here may ever be
  -- joined on a partner-supplied name. SHOULD move to definitions.json -> a seed when it changes.
  SELECT * FROM UNNEST([
    STRUCT('61A007' AS source_id, 'Final Funnel'     AS vendor, 'APAC' AS theatre),
    ('B75F75', 'Roverpath',        'APAC'),
    ('D9E103', 'VRSM Lead Magnet', 'APAC'),
    ('F5F5DD', 'DemandAI',         'APAC'),
    ('2DE5BB', 'Interlink',        'APAC'),
    ('D164E3', 'SitPub',           'APAC'),
    ('9E8948', 'Final Funnel',     'EMEA'),
    ('41710C', 'Roverpath',        'EMEA'),
    ('00EC71', 'Pipeline360',      'EMEA'),
    ('1EF986', 'Inbox Insight',    'EMEA'),
    ('929C51', 'Acquisition',      'EMEA')
  ])
),
deduped AS (
  SELECT
    TO_HEX(SHA256(LOWER(TRIM(EMAIL))))                        AS LEAD_KEY,
    LEAD_CAMPAIGN_NAME                                        AS CAMPAIGN,
    SOURCE_ID,
    STATUS                                                    AS INTEGRATE_STATUS,
    DISPOSITION_CODE,
    -- CUSTOM_REASON (column K) is free text and DOES carry PII: 7 rows embed a lead's own email
    -- in the duplicate-rejection message. Scrubbed HERE, once, so no consumer can forget. A
    -- general pattern, not a fix aimed at those 7 - the message echoes whatever the source
    -- sends. `&#44,` is the source's own HTML entity for a comma and is decoded in the same pass.
    REPLACE(
      REGEXP_REPLACE(CUSTOM_REASON,
                     r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '<redacted>'),
      '&#44,', ',')                                           AS REASON_TEXT,
    -- Offer from the landing path. Anchored on the trailing token, never a bare substring:
    -- `-pulse-survey` and `-qualification-que` are the two forms observed, and the truncated
    -- second one is the SOURCE's own spelling, not a typo here. NULL (not 'Lead Magnet') when
    -- the URL is absent or matches neither - an absent URL is UNKNOWN, and letting it default
    -- to a real offer is how a lead silently lands in the wrong population.
    CASE
      WHEN LOWER(URL) LIKE '%-pulse-survey%'      THEN 'Pulse Survey'
      WHEN LOWER(URL) LIKE '%-qualification-que%' THEN 'Qualification Questions'
      ELSE NULL
    END                                                       AS OFFER_FROM_URL,
    URL IS NOT NULL AND TRIM(URL) <> ''                       AS HAS_URL,
    -- Did INTEGRATE hold an enrichment for this lead? A BOOLEAN, never the number - the
    -- figure sql/20 needs is a COUNT, and emitting the phone itself would put PII into a
    -- view that exists to keep it out. The Salesforce copy stays the only source of the
    -- actual digits, so the staff detail table is unaffected.
    --
    -- The test mirrors sql/20's ONE normalisation (not a sentinel copy): not blank, not a
    -- known sentinel, and CONTAINS A DIGIT. Integrate never writes '-' (verified: zero rows
    -- table-wide) but the sentinel arm stays, because the guard that matters is the digit -
    -- it is what makes the next unannounced sentinel fail CLOSED instead of inflating a rate.
    (   TRIM(IFNULL(ENRICHED_PHONE_NUMBER, '')) <> ''
    AND UPPER(TRIM(ENRICHED_PHONE_NUMBER)) NOT IN ('NA', 'N/A', 'NONE', 'UNKNOWN', '-')
    AND REGEXP_CONTAINS(ENRICHED_PHONE_NUMBER, r'[0-9]')  )               AS HAS_ENRICHED
  FROM `bidbrain-analytics.raw_snowflake.integrate_leads`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY TO_HEX(SHA256(LOWER(TRIM(EMAIL)))), LEAD_CAMPAIGN_NAME
    ORDER BY SAFE.PARSE_TIMESTAMP('%m/%d/%Y %H:%M:%S', UPDATED_TIMESTAMP) DESC,
             DISPOSITION_CODE
  ) = 1
)
SELECT
  d.LEAD_KEY,
  d.CAMPAIGN,
  d.SOURCE_ID,
  -- Our spelling of the vendor, resolved through the dictionary. A source id Integrate sends
  -- that is NOT in the dictionary resolves to NULL and is counted by the job's audit line -
  -- never silently folded into a neighbouring vendor.
  m.vendor                                                    AS VENDOR,
  m.theatre                                                   AS THEATRE,
  d.INTEGRATE_STATUS,
  d.DISPOSITION_CODE,
  d.REASON_TEXT,
  d.OFFER_FROM_URL,
  d.HAS_URL,
  d.HAS_ENRICHED
FROM deduped d
LEFT JOIN source_map m ON m.source_id = d.SOURCE_ID
