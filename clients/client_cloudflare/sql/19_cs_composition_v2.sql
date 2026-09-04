-- =====================================================================
-- client_cloudflare.cs_composition_v2
-- The five COMPOSITION DONUTS (Solutions / Country / Job function / Job level /
-- Professional demographic) for a theatre the legacy model does not cover.
-- Grain: THEATRE x BOOK x VENDOR x MARKET x DIM x VALUE. LONG format, campaign to date.
-- Feeds the export job's `cs_composition` payload block ONLY.
-- =====================================================================
-- WHY THIS EXISTS (2026-09-05, client: "these updates we are doing for APJ do it on
-- EMEA too"):
--   The APJ donuts aggregate the LEGACY lead rows (salesforce_leads_live, APAC-only by its
--   13-ID allowlist) in the browser. EMEA has no lead-grain rows in the payload at all -
--   17_cs_pacing_v2 is week x market x vendor and 18_cs_compare_v2 is day x market x
--   country x asset - so the donut cards were simply HIDDEN off-theatre. This is the
--   smallest read that fills them: one row per (scope, dimension, value) with the count
--   of accepted leads, plus the New backlog for the Admin View.
--
-- WHY LONG FORMAT, AND WHY NO DAY:
--   * Five dimensions in one view means one payload block and one dashboard reader; a
--     wide row per lead would ship PII-adjacent detail (a job TITLE against a market at
--     lead grain) for no gain. Counts per value are what the ring draws.
--   * The EMEA CS tab has NO date control (dateControl is per tab on that lane; the top
--     band is campaign-to-date), so the donuts are campaign-to-date too, exactly like the
--     band they sit under. Adding DAY would multiply the rows ~60x to honour a filter that
--     does not exist there.
--
-- SCOPE IS THE DASHBOARD'S JOB, NOT THIS VIEW'S: it carries THEATRE, BOOK, VENDOR and
-- MARKET so cspdScopeOk() - the ONE predicate behind cspdRows() - filters it to exactly
-- the scope the top band reads. Both theatres are here on purpose (the 18_* reasoning):
-- a view silently holding one theatre is a trap the day APJ migrates, and the theatre
-- column is what makes "no data spills between lanes" a filter the dashboard applies and
-- the job can assert, not a hope.
--
-- POPULATION = accepted (+ New). The APJ donuts draw ACCEPTED leads, and accepted + New
-- when the Admin View is on (aggregate()'s breakdownLeads). Rejected leads are not in any
-- composition chart, so they are not here either - shipping them would invite a consumer
-- to sum a column the rings never draw.
--
-- BLANK -> 'Unknown', the same label aggregate()'s lbl() gives a blank on APJ, so a lead
-- with no job level is a visible slice on both theatres, never a dropped row. It is what
-- lets every dimension sum to the SAME total, which the job asserts below and the
-- dashboard checks against the scoped total (an "Unaccounted" slice if it ever fails).
--
-- RATES ARE ABSENT ON PURPOSE (md/AGENTS.md). Every consumer sums these counts.
-- =====================================================================
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_composition_v2` AS
WITH population AS (
  SELECT
    THEATRE, BOOK, VENDOR, MARKET,
    IS_ACCEPTED, IS_UNPROCESSED,
    SERVICE, COUNTRY_NAME, JOB_FUNCTION, JOB_LEVEL, JOB_TITLE
  FROM `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2`
  WHERE IS_ACCEPTED = 1 OR IS_UNPROCESSED = 1
),
long AS (
  -- DIM names are the dashboard's own keys (aggregate() returns solutions / countries /
  -- jobFunc / jobLevel / jobTitle) so the reader is a lookup, not a translation table.
  SELECT THEATRE, BOOK, VENDOR, MARKET, 'solutions'  AS DIM, SERVICE       AS VALUE, IS_ACCEPTED, IS_UNPROCESSED FROM population
  UNION ALL
  SELECT THEATRE, BOOK, VENDOR, MARKET, 'countries'  AS DIM, COUNTRY_NAME  AS VALUE, IS_ACCEPTED, IS_UNPROCESSED FROM population
  UNION ALL
  SELECT THEATRE, BOOK, VENDOR, MARKET, 'jobFunc'    AS DIM, JOB_FUNCTION  AS VALUE, IS_ACCEPTED, IS_UNPROCESSED FROM population
  UNION ALL
  SELECT THEATRE, BOOK, VENDOR, MARKET, 'jobLevel'   AS DIM, JOB_LEVEL     AS VALUE, IS_ACCEPTED, IS_UNPROCESSED FROM population
  UNION ALL
  SELECT THEATRE, BOOK, VENDOR, MARKET, 'jobTitle'   AS DIM, JOB_TITLE     AS VALUE, IS_ACCEPTED, IS_UNPROCESSED FROM population
)
SELECT
  THEATRE,
  BOOK,
  VENDOR,
  MARKET,
  DIM,
  IF(TRIM(IFNULL(VALUE, '')) = '', 'Unknown', TRIM(VALUE)) AS VALUE,
  SUM(IS_ACCEPTED)    AS ACCEPTED,
  SUM(IS_UNPROCESSED) AS UNPROCESSED
FROM long
GROUP BY 1, 2, 3, 4, 5, 6
;
