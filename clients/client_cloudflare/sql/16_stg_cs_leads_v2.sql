-- =====================================================================
-- client_cloudflare.stg_cs_leads_v2
-- Canonical Content-Syndication lead grain for the "Pacing detail" section.
-- Grain carries THEATRE (APAC | EMEA) x BOOK (Core DG | Regional) x MARKET x
-- VENDOR (= publisher). Feeds 17_cs_pacing_v2 ONLY.
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
-- NOT a pure 1:1 port in one respect: the Transmission TEST-LEAD filter from
-- 10_salesforce_leads_live is applied here too (added 2026-08-27). Without it the two
-- models counted different lead universes and the same CS tab showed two totals.
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
    -- Exclude Transmission TEST leads. IDENTICAL predicate to 10_salesforce_leads_live
    -- (added there 2026-07-07 per the Jade call); it was missing here from the day this
    -- view was written, and that was the whole reason the APJ KPI strip (which reads 10_*)
    -- and the Pacing detail band (which reads this) disagreed on the same screen:
    -- 12 test leads counted as APAC delivery (10 accepted / 2 rejected) plus 1 sitting
    -- unprocessed on EMEA. Keep the two predicates character-for-character the same - the
    -- models are only guaranteed to agree for as long as they are.
    --
    -- Match on the email DOMAIN, never on the string 'test' anywhere: a real rejected lead
    -- from Advantest Corporation (advantest.com) carries 'test' inside the company name and
    -- inside its domain, and a naive 'test' match would silently drop a genuine client lead.
    -- The only domain this catches today is transmissionagency.com (13 leads at 2026-08-27);
    -- the substring keeps transmission.com and any other variant covered.
    AND LOWER(IFNULL(SPLIT(EMAIL, '@')[SAFE_OFFSET(1)], '')) NOT LIKE '%transmission%'
),
typed AS (
  SELECT
    DAY, LEAD_STATUS, CAMPAIGN, CAMPAIGN_ID, COUNTRY_NAME, SEG_PROGRAM,
    IF(UPPER(SEG_REGION) LIKE 'EMEA%', 'EMEA', 'APAC') AS THEATRE,
    -- VENDOR (= the publisher) display names. Salesforce carries the same publisher in
    -- several casings - SHOUTY for the ones onboarded most recently (DEMANDAI, INTERLINK,
    -- PIPELINE360, INBOXINSIGHT), title case for the older ones - so the dashboard's vendor
    -- picker used to read "Roverpath, Final Funnel, PIPELINE360". This is the same class of
    -- key as the ASSET names (md/AGENTS.md): a partner-supplied NAME needs an alias map and a
    -- VISIBLE fallback. Unmapped spellings fall through UNCHANGED - a new publisher shows up
    -- under whatever the feed calls it, which looks unfamiliar rather than looking broken.
    --
    -- TWO of these entries are load-bearing beyond cosmetics:
    --   * VSRM is the spelling in the feed, VRSM the one on the client's sheet and in the
    --     targets seed. Alias here so the target join in 17_* can never miss.
    --   * 'Roverpath' and 'Final Funnel' MUST fall through the ELSE untouched for the same
    --     reason - they are the join keys for 1,720 of the seeded target rows.
    CASE UPPER(SEG_VENDOR)
      WHEN 'VSRM LEAD MAGNET' THEN 'VRSM Lead Magnet'
      WHEN 'DEMANDAI'         THEN 'DemandAI'
      WHEN 'INTERLINK'        THEN 'Interlink'
      WHEN 'PIPELINE360'      THEN 'Pipeline360'
      WHEN 'INBOXINSIGHT'     THEN 'Inbox Insight'
      ELSE SEG_VENDOR
    END AS VENDOR,
    -- BOOK: which plan the campaign is bought under. Added 2026-08-27 on Lydia's request to
    -- put the REGIONAL campaigns/publishers (DemandAI, Interlink, and SitPub when it starts
    -- delivering) on the pacing dashboard - they were dropped entirely before this.
    --
    -- It is a SEPARATE dimension from THEATRE, and must stay one: ANZ DnB runs in ANZ, which
    -- is APAC, on the same Monday week anchor. Modelling it as a third theatre (which the old
    -- comment in the dashboard suggested) would have been a lie about the region.
    --
    -- The Core DG list is EXPLICIT, and the residual is 'Unclassified' rather than an
    -- `ELSE 'Core DG'`. md/AGENTS.md: a CASE with a real-value ELSE on a parsed token turns a
    -- feed change into SILENT misattribution. That matters more here than almost anywhere,
    -- because the Core DG band reconciles against a FIXED seeded target (APAC 2,290 /
    -- EMEA 830): a new programme folded into Core DG would inflate delivery against a target
    -- that never grew, and the pacing figure would quietly overstate. This feed churns fast -
    -- GENERAL, VER-RETAIL and EXP all appeared inside one week in Aug 2026 - so assume a
    -- ninth programme is coming. 'Unclassified' is COUNTED, is selectable in the dashboard's
    -- campaign picker and is WARNED about in the job log; nothing is ever dropped.
    -- Adding a programme = one line here, and the job log names it for you.
    CASE
      WHEN SEG_PROGRAM = 'ANZ DnB' THEN 'Regional'
      WHEN SEG_PROGRAM IN ('CF1', 'GENERAL', 'Tier 3', 'All Verticals', 'Japan Tier 2',
                           'VER-DIGITAL NATIVE', 'VER-FINANCE', 'VER-RETAIL') THEN 'Core DG'
      ELSE 'Unclassified'
    END AS BOOK,
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
  -- ANZ DnB (DemandAI / Interlink) USED TO BE EXCLUDED HERE. It is now IN, as its own BOOK -
  -- see the BOOK CASE above. It has no seeded targets, so it surfaces as delivery with no
  -- pacing, exactly like Pipeline360 did; that is correct and must not be suppressed.
  --
  -- Still out of scope, both deliberately:
  --   * SEG_PROGRAM 'EXP' - the expansion motion, not a Content-Syndication demand-gen buy.
  --   * VENDOR 'ACQUISITION' - NOT a publisher. Those campaign names are shaped differently
  --     (e.g. 2026_Q3_EMEA-DACH_ACQUISITION_EXP_CF1_... carries an extra segment), so the
  --     vendor-position token is a motion label and every downstream offset is shifted by
  --     one. 482 rows at 2026-08-27, ALL still LEAD_STATUS='New' (zero delivered), so nothing
  --     is being hidden from a pacing figure. Revisit if Transmission regularises the naming.
  SELECT * FROM typed
  WHERE SEG_PROGRAM <> 'EXP'
    AND UPPER(VENDOR) <> 'ACQUISITION'
)
SELECT
  THEATRE,
  BOOK,
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
