-- =====================================================================
-- client_cloudflare.cs_pacing_v2
-- book x week x market x vendor, actuals FULL OUTER JOINed to targets.
-- The single view the export job reads for the "Pacing detail" section.
-- =====================================================================
-- Ported from Transmission's CS_REPORTING.V_CS_PACING_V2. Two differences,
-- both because this runs in BigQuery over a committed seed:
--
--   * targets come from client_cloudflare.seed_cs_targets_q3, loaded from the
--     VERSION-CONTROLLED targets/cs_targets_q3.csv (the repo's committed-CSV->BQ
--     standard for targets, so anyone who clones can reproduce the table) rather
--     than from 468 hand-pasted VALUES rows in DDL.
--   * the seed carries MARKET_SEQ, so the dashboard's market DISPLAY ORDER is
--     data, not code - re-order the CSV and the chart follows with no deploy.
--     This is what keeps the component free of a hardcoded market list.
--
-- AGGREGATED, and deliberately so: this is counts by week/market/vendor with NO
-- lead-level columns, so unlike the `pacing` payload branch (which ships the full
-- lead grain, PII included) this one is safe to render anywhere and adds ~100 KB
-- to the JSON instead of megabytes.
--
-- FULL OUTER JOIN, not LEFT: a future week must show its target with zero
-- actuals (that is the whole pacing grid), AND an actual with no matching target
-- must still appear rather than being dropped. Pipeline360 and Inbox Insight have
-- no targets yet - they will surface with delivery and no pacing, which is
-- correct. Do not "fix" that by making this an inner join.
--
-- BOOK is part of the join key (added 2026-08-27 with the Regional campaigns). The seed
-- carries it too, so the whole grid stays data-driven. It matters that it is in the KEY:
-- the Regional book has no targets, and without BOOK on both sides a Regional ANZ actual
-- would have joined the Core DG ANZ target row for that week and reported someone else's
-- target as its own.
--
-- RATES ARE COMPUTED HERE FOR CONVENIENCE ONLY. They are correct at this grain
-- and MUST NOT be summed by any consumer (md/AGENTS.md "RATES MUST NEVER ENTER A
-- FACT TABLE"). The counts are the additive truth; the dashboard re-derives every
-- rate from the counts after it aggregates, and never reads these columns.
-- They exist so an ad-hoc BQ query does not have to redo the arithmetic.
-- =====================================================================
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_pacing_v2` AS
WITH actual AS (
  SELECT
    THEATRE, BOOK, VENDOR, MARKET, WEEK_START,
    SUM(IS_DELIVERED)   AS DELIVERED,
    SUM(IS_ACCEPTED)    AS ACCEPTED,
    SUM(IS_REJECTED)    AS REJECTED,
    SUM(IS_UNPROCESSED) AS UNPROCESSED,
    SUM(NEEDS_REVIEW)   AS NEEDS_REVIEW
  FROM `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2`
  GROUP BY 1, 2, 3, 4, 5
),
tgt AS (
  SELECT BOOK, THEATRE, VENDOR, MARKET, MARKET_SEQ, WEEK_NUMBER, WEEK_START, TARGET
  FROM `bidbrain-analytics.client_cloudflare.seed_cs_targets_q3`
),
-- One row per theatre/market so an ACTUAL with no target row still gets the
-- market's display position (otherwise a brand-new market would sort to the end
-- of the chart by accident rather than by decision). Deliberately NOT scoped by
-- BOOK: the Regional book has no target rows of its own, and its ANZ delivery
-- should still sort where ANZ sorts. Same reasoning for wnum below.
mseq AS (
  SELECT THEATRE, MARKET, MIN(MARKET_SEQ) AS MARKET_SEQ
  FROM tgt GROUP BY 1, 2
),
-- Same for the week number: an actual landing in a week the targets do not cover
-- should still report which week of the quarter it is.
wnum AS (
  SELECT THEATRE, WEEK_START, MIN(WEEK_NUMBER) AS WEEK_NUMBER
  FROM tgt GROUP BY 1, 2
)
SELECT
  COALESCE(a.THEATRE,    t.THEATRE)    AS THEATRE,
  COALESCE(a.BOOK,       t.BOOK)       AS BOOK,
  COALESCE(a.VENDOR,     t.VENDOR)     AS VENDOR,
  COALESCE(a.MARKET,     t.MARKET)     AS MARKET,
  COALESCE(a.WEEK_START, t.WEEK_START) AS WEEK_START,
  ms.MARKET_SEQ,
  wn.WEEK_NUMBER,
  COALESCE(t.TARGET,        0) AS TARGET,
  COALESCE(a.DELIVERED,     0) AS DELIVERED,
  COALESCE(a.ACCEPTED,      0) AS ACCEPTED,
  COALESCE(a.REJECTED,      0) AS REJECTED,
  COALESCE(a.UNPROCESSED,   0) AS UNPROCESSED,
  COALESCE(a.NEEDS_REVIEW,  0) AS NEEDS_REVIEW,
  -- convenience rates - see the header note; never SUM these
  SAFE_DIVIDE(COALESCE(a.REJECTED,  0), NULLIF(COALESCE(a.DELIVERED, 0), 0)) AS REJECTION_RATE,
  SAFE_DIVIDE(COALESCE(a.ACCEPTED,  0), NULLIF(COALESCE(a.DELIVERED, 0), 0)) AS ACCEPTANCE_RATE,
  SAFE_DIVIDE(COALESCE(a.DELIVERED, 0), NULLIF(COALESCE(t.TARGET,    0), 0)) AS WEEKLY_PACING,
  COALESCE(t.TARGET, 0) - COALESCE(a.ACCEPTED, 0)                            AS LEAD_DEFICIT
FROM actual a
FULL OUTER JOIN tgt t
  ON  a.THEATRE    = t.THEATRE
  AND a.BOOK       = t.BOOK
  AND a.VENDOR     = t.VENDOR
  AND a.MARKET     = t.MARKET
  AND a.WEEK_START = t.WEEK_START
LEFT JOIN mseq ms
  ON  ms.THEATRE = COALESCE(a.THEATRE, t.THEATRE)
  AND ms.MARKET  = COALESCE(a.MARKET,  t.MARKET)
LEFT JOIN wnum wn
  ON  wn.THEATRE    = COALESCE(a.THEATRE,    t.THEATRE)
  AND wn.WEEK_START = COALESCE(a.WEEK_START, t.WEEK_START)
;
