-- =====================================================================
-- client_cloudflare.cs_compare_v2
-- Lead-grain-derived aggregate for the CS COMPARISON tab's side-by-side panels.
-- Grain: THEATRE x BOOK x VENDOR x MARKET x COUNTRY x DAY x SERVICE x ASSET.
-- Feeds the export job's `cs_compare` payload block ONLY.
-- =====================================================================
-- WHY THIS EXISTS ALONGSIDE 17_cs_pacing_v2:
--   17_* is aggregated to week x market x vendor, which is everything the "Pacing
--   detail" band needs. The Comparison panels need three things it threw away:
--     * COUNTRY  - the panels' optional country drill-down (EMEA spans 47 countries;
--                  UKI alone has 13).
--     * ASSET    - the "Best performing assets" list.
--     * DAY      - the Comparison tab is DATE-RANGE driven, and a range that cuts
--                  mid-week cannot be honoured from week buckets.
--   So this is a parallel, finer read of the SAME stg_cs_leads_v2 rows. It carries NO
--   targets: those already ship on the `cs_pacing` block at their own (market x week)
--   grain, and duplicating them here would be a second copy of a number that must agree.
--
-- WEEK_START IS CARRIED, NOT DERIVED CLIENT-SIDE. The week anchor is theatre-specific
-- (EMEA commences FRIDAY from 2026-07-31, APAC MONDAY from 2026-07-06) with a pre-anchor
-- clamp - see 16_stg_cs_leads_v2. Re-deriving that in JS would be a third copy of a rule
-- that has already been got wrong twice (the negative-MOD and the missing clamp), so the
-- day rows carry the bucket their own theatre assigned them.
--
-- BOTH THEATRES, deliberately. Only EMEA reads it today (the APJ panels still run off the
-- legacy salesforce_leads_live model, which is untouched), but a view that silently held
-- one theatre would be its own trap the day APJ is migrated onto it - and it is what lets
-- anyone reconcile the two models against each other. At 1,213 rows for the full quarter
-- the whole block is ~120 KB of JSON, so scoping it to EMEA would save nothing worth the
-- asymmetry.
--
-- RATES ARE ABSENT ON PURPOSE (md/AGENTS.md "RATES MUST NEVER ENTER A FACT TABLE"). Every
-- consumer sums these counts and re-derives acceptance / rejection from the sums.
-- =====================================================================
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_compare_v2` AS
SELECT
  THEATRE,
  BOOK,
  VENDOR,
  MARKET,
  -- NULL and '' both mean "the feed did not say", and they must not become two buckets in
  -- the panel's country picker. Normalised to NULL here and rendered as an explicit
  -- "(not stated)" option client-side, never folded into a real country.
  NULLIF(TRIM(IFNULL(COUNTRY_NAME, '')), '') AS COUNTRY_NAME,
  DAY,
  WEEK_START,
  SERVICE,
  -- The RAW asset string. The dashboard owns the folding (ASSET_ALIASES / assetId /
  -- prettyAssetName): Salesforce carries a second naming convention for assets that already
  -- have short codes - the file slug - and EMEA is almost ENTIRELY the slug form
  -- (26Q3_EBOOK_accelerating-ai-adoption-with-sase), with one short code (A-MSM-11) leading
  -- at 417 leads. Folding here would hide a new variant; folding in the dashboard renders an
  -- unmapped one as prose so it looks unfamiliar rather than looking broken (md/AGENTS.md).
  ASSET_1,
  COUNT(*)            AS LEADS,
  SUM(IS_DELIVERED)   AS DELIVERED,
  SUM(IS_ACCEPTED)    AS ACCEPTED,
  SUM(IS_REJECTED)    AS REJECTED,
  SUM(IS_UNPROCESSED) AS UNPROCESSED,
  SUM(NEEDS_REVIEW)   AS NEEDS_REVIEW
FROM `bidbrain-analytics.client_cloudflare.stg_cs_leads_v2`
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
;
