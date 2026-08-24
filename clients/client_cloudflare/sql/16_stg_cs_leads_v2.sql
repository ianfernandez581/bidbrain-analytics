-- =====================================================================
-- client_cloudflare.stg_cs_leads_v2
-- Canonical Content-Syndication lead grain for the "Pacing detail" section
-- (Core DG, APAC + EMEA). Feeds 17_cs_pacing_v2 ONLY.
-- =====================================================================
-- WHY THIS EXISTS ALONGSIDE 10_salesforce_leads_live (which is untouched):
--   10_* is scoped by a hardcoded campaign-ID allowlist (`seed_cs_campaign_ids`)
--   and so is APAC-ONLY - verified 2026-08-24: 5,873 rows, ZERO EMEA. Every
--   headline CS number, donut, QoQ figure and status-dashboard accuracy check on
--   this client hangs off it, so it is deliberately NOT modified here. This view
--   is a SECOND, parallel read of the same raw mirror that scopes by CAMPAIGN
--   NAME instead, which is what brings EMEA in and lets a new vendor appear on
--   its own rather than silently vanishing until someone edits the allowlist.
--   Nothing downstream of 10_* reads this view, so it cannot move a live number.
--
-- Ported 1:1 from Transmission's CS_REPORTING.V_CS_LEADS_V2 (Snowflake). Our
-- pipeline role on CLOUDFLARE_SANDBOX is read-only, and the base table is ALREADY
-- in the shared mirror (raw_snowflake.salesforce_cs_apac_all) and ALREADY in this
-- client's freshness gate, so the model lives in BigQuery like every other
-- client_cloudflare view. Reconciled against the client's own pacing sheet on
-- 2026-08-24: EMEA target 830 / delivered 234 / accepted 208 / rejected 26,
-- needs_review 0 in both theatres. APAC delivery runs AHEAD of the sheet because
-- this is live off Salesforce and the sheet is a snapshot.
--
-- Campaign name shape:  2026_Q3_<region>_<vendor>_<program>_...
--                       seg 3 = region, seg 4 = vendor, seg 5 = program
--
-- ON THE FIXED SPLIT OFFSETS (see md/AGENTS.md "Campaign names are NOT stable
-- keys"): the offsets below are anchored to the `2026_Q3` token that the WHERE
-- clause also matches on. If Transmission ever prefixes these Salesforce campaign
-- names with a brief number, STARTS_WITH stops matching and this view returns
-- ZERO rows - a loud, total failure, NOT the silent one-field shift that bit
-- mongodb. job/main.py asserts on exactly that (it warns when the base table has
-- Q3 rows but this view has none), so the failure surfaces in the job log rather
-- than as a quietly emptier dashboard.
--
-- `_` IS A LIKE WILDCARD, so the scope predicate is STARTS_WITH, never
-- LIKE '2026_Q3%' (repo-wide rule; verified a no-op today at 1,974 rows either
-- way, so this is forward protection).
-- =====================================================================
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2` AS
WITH base AS (
  SELECT
    DAY,
    LEAD_STATUS,
    CAMPAIGN,
    CAMPAIGN_ID,
    COUNTRY_NAME,
    SPLIT(CAMPAIGN, '_')[SAFE_OFFSET(2)] AS SEG_REGION,
    SPLIT(CAMPAIGN, '_')[SAFE_OFFSET(3)] AS SEG_VENDOR,
    SPLIT(CAMPAIGN, '_')[SAFE_OFFSET(4)] AS SEG_PROGRAM
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
  WHERE STARTS_WITH(CAMPAIGN, '2026_Q3')
),
typed AS (
  SELECT
    DAY, LEAD_STATUS, CAMPAIGN, CAMPAIGN_ID, COUNTRY_NAME, SEG_PROGRAM,
    IF(UPPER(SEG_REGION) LIKE 'EMEA%', 'EMEA', 'APAC') AS THEATRE,
    -- VSRM is the spelling in the feed, VRSM the one on the client's sheet and in
    -- the targets seed. Alias here so the target join can never miss.
    IF(UPPER(SEG_VENDOR) = 'VSRM LEAD MAGNET', 'VRSM Lead Magnet', SEG_VENDOR) AS VENDOR,
    -- Market comes from the CAMPAIGN, not COUNTRY_NAME: that is what removes the
    -- RIG fallback and the 'Viet Nam' mis-bucketing the legacy model carries.
    -- Anything unrecognised becomes UNMAPPED and is COUNTED AND SURFACED (the
    -- dashboard prints the count) rather than folded into a real market - an
    -- `ELSE '<a real market>'` here would turn a parse break into silent
    -- misattribution, which is the exact failure mode md/AGENTS.md calls out.
    CASE SEG_REGION
      WHEN 'ANZ'        THEN 'ANZ'     WHEN 'ASEAN'      THEN 'ASEAN'
      WHEN 'SAARC'      THEN 'SAARC'   WHEN 'GCR - CN'   THEN 'GCR-CN'
      WHEN 'TW - CN'    THEN 'GCR-TW'  WHEN 'HK - CN'    THEN 'GCR-HK'
      WHEN 'Japan'      THEN 'Japan'   WHEN 'Korea'      THEN 'Korea'
      WHEN 'EMEA-UKI'   THEN 'UKI'     WHEN 'EMEA-DACH'  THEN 'DACH'
      WHEN 'EMEA-SEUR'  THEN 'SEUR'    WHEN 'EMEA-NEUR'  THEN 'NEUR'
      WHEN 'EMEA-CEERI' THEN 'CEERI'   WHEN 'EMEA-META'  THEN 'MEA'
      ELSE 'UNMAPPED'
    END AS MARKET
  FROM base
),
scoped AS (
  -- Out of scope for this section: the ANZ DnB program (its own book, DEMANDAI /
  -- INTERLINK) and the unlaunched ACQUISITION vendor.
  SELECT * FROM typed
  WHERE SEG_PROGRAM NOT IN ('ANZ DnB', 'EXP')
    AND VENDOR <> 'ACQUISITION'
)
SELECT
  THEATRE,
  MARKET,
  VENDOR,
  SEG_PROGRAM AS PROGRAM,
  DAY,
  -- Week anchors differ by theatre: APAC weeks commence MONDAY from 2026-07-06,
  -- EMEA weeks commence FRIDAY from 2026-08-07.
  --
  -- TWO deliberate deviations from the Snowflake original, both load-bearing:
  --
  -- 1. MOD(MOD(x,7)+7,7), not MOD(x,7). For a day BEFORE the anchor, DATE_DIFF is
  --    negative and MOD returns a negative, which SUBTRACTS a negative and lands
  --    the "week start" AFTER the lead date. Live cases on 2026-08-24: 26 EMEA
  --    leads dated 2026-08-06 (one day before the Friday anchor - 8.5% of all EMEA
  --    delivery) and 5 APAC leads back to 2026-03-25.
  -- 2. GREATEST(..., anchor) clamps anything pre-anchor into week 1 rather than
  --    inventing a week outside the quarter's 13-week grid. The dashboard renders
  --    the grid, so an out-of-grid week would DROP those leads from every weekly
  --    figure while still counting them in the campaign-to-date total - the two
  --    would silently stop reconciling. With the clamp, sum-of-weeks == total
  --    exactly (verified: EMEA 234, APAC 1,591).
  --
  -- The trade-off is that week 1 carries a little pre-anchor spill. That is
  -- visible and reconciles; a missing lead is neither.
  GREATEST(
    DATE_SUB(DAY, INTERVAL MOD(MOD(DATE_DIFF(
      DAY, IF(THEATRE = 'EMEA', DATE '2026-08-07', DATE '2026-07-06'), DAY), 7) + 7, 7) DAY),
    IF(THEATRE = 'EMEA', DATE '2026-08-07', DATE '2026-07-06')
  ) AS WEEK_START,
  LEAD_STATUS,
  IF(LEAD_STATUS = 'Accepted', 1, 0)                     AS IS_ACCEPTED,
  IF(LEAD_STATUS = 'Rejected', 1, 0)                     AS IS_REJECTED,
  IF(LEAD_STATUS = 'New', 1, 0)                          AS IS_UNPROCESSED,
  IF(LEAD_STATUS IN ('Accepted', 'Rejected'), 1, 0)      AS IS_DELIVERED,
  IF(MARKET = 'UNMAPPED', 1, 0)                          AS NEEDS_REVIEW,
  CAMPAIGN,
  CAMPAIGN_ID,
  COUNTRY_NAME
FROM scoped
;
