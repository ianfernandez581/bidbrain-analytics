-- 21_integrate_dispositions.sql
--
-- WEEKLY REJECTION REASONS BY VENDOR (client request 2026-09-17, Jade, via Fahad).
--
-- The Salesforce mirror tells us a lead was Rejected; it never says WHY. The reason lives
-- upstream at Integrate, is captured by CaptureIQ, and lands in Snowflake as INTEGRATE_LEADS
-- (Nabeel, 2026-09-18). This view is the ONLY place the two are joined.
--
-- WHAT THIS VIEW EMITS: aggregates ONLY. Never a lead, never a name, email, phone or address.
-- INTEGRATE_LEADS is a heavy-PII table (first/last name, email, phone, street, postcode on
-- every row) and it is mirrored whole by the `SELECT *` loader. Everything downstream of here
-- reads THIS view, never the raw table - the raw table must not reach job/main.py.
--
-- ---------------------------------------------------------------------------------------
-- THE JOIN. Integrate carries NO Salesforce id. Its LEAD_ID is Integrate's own 36-char GUID
-- and nothing in the 43-column export maps to LEAD_ID_SF. The only shared identifier is
-- EMAIL, which is not unique on its own (5,558 distinct across 5,659 rows), so the key is
-- EMAIL + CAMPAIGN - LEAD_CAMPAIGN_NAME holds our CAMPAIGN string verbatim.
-- Measured 2026-09-18: of 5,682 dispositioned leads in scope, 5,559 match exactly one row
-- (97.8%), 99 match none, 24 fan out. THAT IS NOT 1:1 AND THE VIEW SAYS SO - see COVERAGE.
--
-- FAN-OUT TIE-BREAK: latest UPDATED_TIMESTAMP wins, DISPOSITION_CODE alphabetical as the
-- deterministic second key, so two runs can never disagree. Measured: of the 24 fan-out
-- groups, 18 agree on the code and all 24 agree on STATUS; every one of the 6 disagreements
-- is an ACCEPTED lead moving POSTOUT_SUCCESS -> MQL_MARKET_QUALIFIED_LEAD. No rejected lead
-- fans out with a disagreement, so the tie-break cannot move a figure on this panel today.
--
-- ---------------------------------------------------------------------------------------
-- BUCKETED ON THE SALESFORCE DATE, NEVER ON INTEGRATE'S OWN TIMESTAMPS. Integrate's
-- UPDATED_TIMESTAMP is a MUTATION time (it moves whenever a lead progresses) and
-- FIRST_ACCEPTED_TIMESTAMP is blank on 487 of 768 rejected leads. Bucketing on either would
-- put a reason in a different week from the lead it explains, and every other weekly figure
-- on this dashboard is anchored to the Salesforce lead date.
--
-- COVERAGE IS A FIRST-CLASS OUTPUT, not a footnote. Integrate holds only leads it has
-- dispositioned, and its history does not reach back cleanly: measured per vendor-week,
-- July runs 0-86% while everything from w/c 2026-08-17 is 100%, with ONE exception -
-- Roverpath w/c 2026-09-07 at 46.9%, which is also its largest rejection week of the
-- quarter. A panel that shows "top reason" over half a week's rejections, with no hint that
-- the other half is missing, is worse than one that shows nothing: the 7 Sep Roverpath cell
-- reads "invalid email, 100% of rejections" on 47% coverage. The dashboard suppresses a
-- vendor-week below a threshold and states why; this view gives it the numbers to do that.
--
-- DEMANDAI, INTERLINK AND SITPUB ARE ABSENT FROM INTEGRATE BY DESIGN, not by fault. They are
-- the Regional (ANZ DnB) book; Integrate runs the Core DG plan only. They therefore resolve
-- to ZERO coverage forever, and the dashboard must say "no reason data for this vendor"
-- rather than drawing an empty panel that reads as "no rejections".
--
-- SOURCE_ID is Integrate's own id and is 1:1 to a publisher across the whole table (verified
-- 2026-09-18, 0 violations). The REVERSE is not true - Final Funnel and Roverpath each carry
-- two source ids because they run in both theatres - so anything keyed on publisher alone
-- merges two vendors. Key on SOURCE_ID, or on VENDOR + THEATRE, never VENDOR.
--
-- SOURCE_MAP mirrors the "Integrate Source Details" sheet (Nabeel, 2026-09-18). It is inline
-- here deliberately for this first cut and SHOULD MOVE INTO definitions.json -> a seed table
-- the day it changes, like every other campaign/vendor list in this client. Three of its 11
-- publisher spellings differ from ours (VSRM / SitPub / Inbox Insights), which is why the map
-- carries OUR name as well as theirs - never join these two feeds on a partner-supplied name.

CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.integrate_dispositions` AS
WITH
-- Vendor, theatre, source id, disposition and the scrubbed reason all come from the bridge -
-- sql/21 is the ONLY reader of raw_snowflake.integrate_leads, and the only place the dedupe
-- tie-break and the PII scrub are defined. This view adds the weekly aggregation and the
-- coverage arithmetic on top; it must never re-derive either.
integrate AS (
  SELECT LEAD_KEY, CAMPAIGN, SOURCE_ID, VENDOR, THEATRE,
         DISPOSITION_CODE, INTEGRATE_STATUS
  FROM `bidbrain-analytics.client_cloudflare.integrate_bridge`
  WHERE VENDOR IS NOT NULL          -- an unmapped source id is audited by the job, not folded
),

-- Our rejected leads. Read from the RAW mirror because stg_cs_leads_v2 carries no lead-level
-- key at all (no email, no LEAD_ID_SF), and adding one there would put PII into the view that
-- feeds the client payload. The scope below is the campaign allowlist stg_cs_leads_v2 itself
-- resolves from, read from the SAME seed tables - not a second copy of the predicate.
sf_rejected AS (
  SELECT
    TO_HEX(SHA256(LOWER(TRIM(EMAIL))))                        AS lead_key,
    CAMPAIGN                                                  AS campaign,
    DATE_TRUNC(DAY, WEEK(MONDAY))                             AS week_start
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
  WHERE LEAD_STATUS = 'Rejected'
    AND DAY >= DATE '2026-07-01'
    AND CAMPAIGN_ID IN (
      SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_cs_campaign_ids`
      UNION DISTINCT
      SELECT campaign_id FROM `bidbrain-analytics.client_cloudflare.seed_cs_emea_campaign_ids`
    )
),

-- The panel's numerator: rejections we can explain.
matched AS (
  SELECT
    s.week_start,
    i.THEATRE  AS theatre,
    i.VENDOR   AS vendor,
    i.SOURCE_ID AS source_id,
    i.DISPOSITION_CODE AS disposition_code,
    -- An ACCEPTED Integrate code on a lead Salesforce rejected is REAL and must not be hidden:
    -- ~12 leads in Q3 carry POSTOUT_SUCCESS / MQL_MARKET_QUALIFIED_LEAD while Salesforce says
    -- Rejected, because Integrate accepted them and the rejection happened downstream. Flagged
    -- so the dashboard can label them rather than let "top rejection reason" read
    -- POSTOUT_SUCCESS.
    i.INTEGRATE_STATUS = 'Accepted'                           AS accepted_upstream,
    COUNT(*)                                                  AS leads
  FROM sf_rejected s
  JOIN integrate  i ON i.LEAD_KEY = s.lead_key AND i.CAMPAIGN = s.campaign
  GROUP BY 1,2,3,4,5,6
),

-- The denominator: every rejection WE hold, whether Integrate explains it or not. Taken from
-- stg_cs_leads_v2 so it ties exactly to the rejected figure the rest of the CS tab prints.
ours AS (
  SELECT THEATRE AS theatre, BOOK AS book, VENDOR AS vendor, WEEK_START AS week_start,
         SUM(IS_REJECTED) AS rejected_total
  FROM `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2`
  WHERE IS_REJECTED = 1 AND DAY >= DATE '2026-07-01'
  GROUP BY 1,2,3,4
)

SELECT
  o.week_start,
  o.theatre,
  o.book,
  o.vendor,
  m.source_id,
  m.disposition_code,
  m.accepted_upstream,
  COALESCE(m.leads, 0)                                        AS leads,
  o.rejected_total,
  -- Rejections in this vendor-week that Integrate explains at all. Repeated on every row of
  -- the group on purpose: the dashboard must be able to render the coverage caption from ANY
  -- single row it is about to draw, without re-aggregating.
  SUM(COALESCE(m.leads, 0)) OVER (PARTITION BY o.week_start, o.theatre, o.vendor)
                                                              AS explained_total,
  SAFE_DIVIDE(
    SUM(COALESCE(m.leads, 0)) OVER (PARTITION BY o.week_start, o.theatre, o.vendor),
    o.rejected_total)                                         AS coverage
FROM ours o
-- LEFT JOIN, never INNER: a vendor-week Integrate cannot explain at all (DemandAI, Interlink,
-- and every vendor before w/c 17 Aug) must still appear, carrying its true rejected_total and
-- a coverage of 0. An INNER JOIN would delete exactly the weeks the reader most needs warning
-- about, and the panel would look complete while silently dropping them.
LEFT JOIN matched m
  ON  m.week_start = o.week_start
  AND m.theatre    = o.theatre
  AND m.vendor     = o.vendor
