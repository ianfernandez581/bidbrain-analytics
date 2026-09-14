-- 01_stg_ttd: filter raw_windsor.perf_the_trade_desk to the Sophiie AI advertiser, at daily x
-- campaign x ad group x creative x ad_format grain. This is the client's slice + the audience-tier /
-- funnel-stage parse + the sign-up conversion unpack. The raw layer IS raw_windsor.perf_the_trade_desk
-- (Windsor TTD connector, self-refreshing via the windsor-tradedesk-ingest job) -- NOT Snowflake.
--
-- ADVERTISER FILTER: The Trade Desk advertiser id `gjcl0pp` (the id in the TTD platform URL,
-- desk.thetradedesk.com/app/home/advertiser/gjcl0pp/...). The id is the stable key. The name arm is an
-- EXACT two-value list, never a LIKE - the advertiser is spelled "Sohiie AI" in The Trade Desk (a typo
-- on the seat), so both spellings are listed and a substring match is deliberately avoided (see the
-- repo-wide "_ is a LIKE wildcard" / "names are not stable keys" rules in md/AGENTS.md).
--
-- AD GROUP NAMING: `<AUDIENCE TIER>_<STAGE CODE>`, e.g. 'TIER1-CALLHEAVY_AWR', 'TIER2-QUOTED_AWR',
-- 'TIER3-PROJECT_AWR', 'RETARGETING_CONSID'. Parsed from the TRAILING token, anchored with a regex,
-- never a fixed SPLIT offset (a fixed offset shifts the moment a prefix is added - the defect that
-- silently dropped a month of MongoDB delivery; md/AGENTS.md "Campaign names are NOT stable keys").
--   AWR    -> Awareness
--   CONSID -> Consideration
--   CONV   -> Conversion            (not in market yet; mapped so a new ad group lands correctly)
-- Anything else -> 'Unclassified', which is DELIBERATE and LOUD: the export job WARNs by ad-group
-- name and the chip shows up on the dashboard. A real-value ELSE here would convert a naming change
-- into silent misattribution instead of a visible one.
--
-- TRY FREE CLICKS: ONE COLUMN, NOT A SUM OVER SLOTS (settled 2026-09-14 against the TTD UI).
-- Windsor exposes TTD conversions ONLY as anonymous numbered slots (click_conversion_NN =
-- post-click, view_through_conversion_NN = post-view), with no pixel name or id in the connector -
-- so which slot is which action cannot be read from the feed. It is read off the campaign's
-- "Configure campaign reporting and attribution" screen and STATED here:
--   column 01 -> Try Free Sign up (s6yku20), cross-device concept PERSON       <- THE headline
--   column 02 -> Try Free Sign up (s6yku20), cross-device concept HOUSEHOLD
--   column 03 -> Talk to sophiie Sign up (qdds2yc)   <- ADDED 2026-09-14, the SECOND outcome
--   column 04 -> the Household twin of column 03, if TTD is emitting one
--   columns 05-12   -> unused
--
-- *** COLUMN 03 HAS HELD TWO DIFFERENT ACTIONS, SO THE MAP IS DATE-AWARE. *** Until 2026-09-11 it
-- was Page Land (57o4sz8), a SITE VISIT pixel, which has since been detached; from 2026-09-12 it is
-- Talk to sophiie. `_talk_era` below is that boundary, and it is the whole reason this view cannot
-- just read a column number. The boundary is currently unambiguous because 2026-09-12 carries rows
-- but ZERO conversions of any kind, so nothing sits on the seam.
-- CAVEAT, and it is the one to watch: TTD reports by CURRENT column assignment, so a Windsor re-pull
-- of an OLD date can restate column 03 with Talk to sophiie values. That would move numbers out of
-- `retired_site_visit_conv` and into the Talk figure for days before the tag existed. If the retired
-- figure starts shrinking run to run, this is why - pin the era on the reporting side, not the feed.
--
-- TWO RULES FALL OUT, and both were being broken:
--  1. COLUMNS 01 AND 02 ARE THE SAME CONVERSIONS TWICE. TTD reports one data source once per
--     cross-device concept - Person (Identity Alliance) and Household (Identity Alliance with
--     Household) - so adding them double counts. We take PERSON, the tighter identity resolution;
--     Household is carried beside it as a diagnostic and must never be added in.
--  2. THE PAGE LAND COLUMNS ARE NOT THIS CAMPAIGN'S OUTCOME. A landing on sophiie.ai is not a Try
--     free click. Summing all 12 slots published 535 site visits as the outcome figure (it read
--     A$11.41 per "sign-up" against a A$150 target - an outcome rate that good is a measurement
--     artefact until proven otherwise). They are kept separately so the history stays auditable and
--     can never be summed back in by a later edit.
--
-- SLOT NUMBERING IS NOT A STABLE KEY - detaching or attaching a data source in TTD renumbers the
-- columns. `unmapped_conv` (05-12) must be 0 and `retired_site_visit_conv` must not advance past
-- 2026-09-11; the export job WARNs by name on either, which is the loud failure that replaces a
-- figure quietly changing meaning. `conv_slots` is still carried for the same reason.
-- `conversion_touch_NN` (TOTAL pixel fires, mostly NOT ad-attributed) is deliberately unused - see
-- clients/client_vmch/sql/03_stg_ttd.sql.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_sophiie.stg_ttd` AS
WITH base AS (
  SELECT *, PARSE_JSON(JSON_VALUE(conversions)) AS _conv
  FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
  WHERE advertiser_id = 'gjcl0pp'
     OR LOWER(TRIM(advertiser_name)) IN ('sohiie ai', 'sophiie ai')
),
parsed AS (
  SELECT
    *,
    TRIM(ad_group_name) AS _ag,
    -- Trailing stage code, anchored on the final underscore-delimited token. UPPER so a
    -- lower-cased rename still resolves.
    UPPER(REGEXP_EXTRACT(TRIM(ad_group_name), r'_([A-Za-z]+)$')) AS _stage_code,
    -- Everything before that token = the audience tier ('TIER1-CALLHEAVY'). If the name carries no
    -- trailing stage code the whole name IS the tier, so a rename never blanks the label.
    -- UPPER + a leading `<digits>_` strip: Transmission is progressively prefixing names with the
    -- brief number, and without the strip a `2479_` prefix would silently retitle every tier
    -- ("2479 Tier1 Callheavy") even though the STAGE, anchored to the trailing token, is unaffected.
    -- See md/AGENTS.md "Campaign names are NOT stable keys".
    UPPER(REGEXP_REPLACE(
      COALESCE(REGEXP_EXTRACT(TRIM(ad_group_name), r'^(.*)_[A-Za-z]+$'), TRIM(ad_group_name)),
      r'^[0-9]+_', '')) AS _tier,
    -- The reporting-column-03 boundary (see the header). 2026-09-11 is the last day that column
    -- belonged to the Page Land site-visit pixel; from 2026-09-12 it is Talk to sophiie Sign up.
    -- ONE definition, read by every column below, so the two eras can never disagree.
    metric_date > DATE '2026-09-11' AS _talk_era
  FROM base
)
SELECT
  metric_date                                                    AS date,
  campaign_id,
  TRIM(campaign_name)                                            AS campaign_name,
  ad_group_id,
  _ag                                                            AS ad_group_name,
  -- Human-readable audience tier: 'TIER1-CALLHEAVY' -> 'Tier 1 - call heavy'. Cosmetic only; every
  -- grouping downstream keys on ad_group_id, never on this label.
  CASE
    WHEN _tier = 'TIER1-CALLHEAVY' THEN 'Tier 1 - call heavy'
    -- The live ad group is TIER2-QUOTELED (verified against real delivery 2026-09-04); TIER2-QUOTED
    -- was the assumed spelling and is kept as an alias so a rename either way still resolves. An
    -- unmapped tier is NOT an error - it falls through to the INITCAP fallback below and rendered as
    -- 'Tier2 Quoteled', which is how this was caught. Cosmetic only: every grouping keys on
    -- ad_group_id, never on this label.
    WHEN _tier IN ('TIER2-QUOTELED', 'TIER2-QUOTED') THEN 'Tier 2 - quote led'
    WHEN _tier = 'TIER3-PROJECT'   THEN 'Tier 3 - project work'
    WHEN _tier = 'TIER4-CONTEXTUAL' THEN 'Tier 4 - contextual'
    WHEN _tier = 'RETARGETING'     THEN 'Retargeting'
    ELSE INITCAP(REPLACE(REPLACE(_tier, '-', ' '), '_', ' '))
  END                                                            AS tier,
  -- Single AU buy. Carried so the shared model keeps a market dimension (every other TTD client has
  -- one) without inventing a split the ad-group names do not carry.
  'Australia'                                                    AS market,
  creative_id,
  TRIM(creative_name)                                            AS creative_name,
  ad_format,
  currency,
  CAST(cost AS FLOAT64)                                          AS spend,
  impressions,
  clicks,
  video_starts,
  video_25,
  video_50,
  video_75,
  video_completes,
  -- Viewability: TTD measures only a SAMPLE, so the rate is viewed/tracked (never
  -- viewed/impressions). Both are NULL until viewability measurement is enabled on the ad groups in
  -- TTD, and NULL must stay distinguishable from a real 0% downstream.
  sampled_viewed_impressions,
  sampled_tracked_impressions,
  -- OUTCOME 1 - Try free sign-ups: reporting column 01 (Person). Never add column 02.
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_01') AS FLOAT64), 0) AS post_view_conv,
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_01') AS FLOAT64), 0) AS post_click_conv,
  -- Column 02 (Household) - the SAME conversions under a wider identity graph, so always >= col 01.
  -- Diagnostic only: the export job prints it so a concept swap in TTD is visible.
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_02') AS FLOAT64), 0) AS post_view_conv_hh,
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_02') AS FLOAT64), 0) AS post_click_conv_hh,
  -- OUTCOME 2 - Talk to sophiie sign-ups: reporting column 03, but ONLY from 2026-09-12. Before
  -- that boundary column 03 was the Page Land site-visit pixel, so reading it flat would credit
  -- this tag with 535 conversions it never earned, dated before it existed.
  IF(_talk_era, COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_03') AS FLOAT64), 0), 0) AS talk_post_view_conv,
  IF(_talk_era, COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_03') AS FLOAT64), 0), 0) AS talk_post_click_conv,
  -- Column 04, the Household twin of 03, on the same boundary. Diagnostic only, never added.
  IF(_talk_era, COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_04') AS FLOAT64), 0), 0) AS talk_post_view_conv_hh,
  IF(_talk_era, COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_04') AS FLOAT64), 0), 0) AS talk_post_click_conv_hh,
  -- The retired Page Land SITE-VISIT pixel: columns 03/04 BEFORE the boundary only. Kept auditable,
  -- deliberately absent from the payload so no later edit can sum a site visit into an outcome.
  IF(_talk_era, 0, COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_03') AS FLOAT64), 0)
              + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_03') AS FLOAT64), 0)
              + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_04') AS FLOAT64), 0)
              + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_04') AS FLOAT64), 0)) AS retired_site_visit_conv,
  -- Columns 05-12: nothing should ever appear here. The job WARNs if it does.
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_12') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_12') AS FLOAT64), 0) ) AS unmapped_conv,
  -- Which anonymous slots the row actually carries, comma-joined. The ONLY way to notice that a
  -- SECOND tracker has started reporting into a different slot - at which point split it out above
  -- rather than leaving two different actions folded into one "sign-ups" number.
  --
  -- JSON_KEYS, not a per-slot test: BigQuery requires a JSONPath to be a CONSTANT expression, so
  -- `JSON_VALUE(_conv, '$.' || k)` over a slot-name array is rejected outright. The Windsor loader
  -- stores ONLY the populated slots in this column (see ingest/windsor_data_pull/tradedesk/
  -- tradedesk_loader.py), so the keys ARE the reporting slots. A slot that reports a literal zero
  -- would be listed too - a false positive in a diagnostic field, which is the safe direction to
  -- err: over-reporting a slot is loud, missing one is silent.
  ARRAY_TO_STRING(JSON_KEYS(_conv), ',')                         AS conv_slots,
  CASE
    WHEN _stage_code = 'AWR'    THEN 'Awareness'
    WHEN _stage_code = 'CONSID' THEN 'Consideration'
    WHEN _stage_code = 'CONV'   THEN 'Conversion'
    -- STATED, not parsed (2026-09-14). The ad group `TIER4-CONTEXTUAL` carries NO trailing stage
    -- token at all - there is nothing to parse - so it fell to 'Unclassified' and put 35,865
    -- impressions / A$133.83 (6% of delivery) under an Unclassified chip on the funnel-stage table.
    -- It is a fourth PROSPECTING tier (contextual targeting), sitting alongside TIER1/2/3 which are
    -- all `_AWR`, so it is Awareness. Keyed on the tier token and listed EXPLICITLY: this is one
    -- named ad group, not a default, so a future unnamed ad group still lands in 'Unclassified' and
    -- still WARNs. If the trafficker renames it to `TIER4-CONTEXTUAL_AWR` the first arm wins and
    -- this becomes a harmless no-op.
    WHEN _tier = 'TIER4-CONTEXTUAL' THEN 'Awareness'
    ELSE 'Unclassified'   -- LOUD on purpose: the job WARNs and the chip appears. Never default this.
  END                                                            AS funnel_stage
FROM parsed
