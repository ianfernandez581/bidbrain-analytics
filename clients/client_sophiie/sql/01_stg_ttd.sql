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
-- SIGN-UPS: Windsor exposes TTD conversions ONLY as anonymous numbered slots
-- (click_conversion_NN = post-click, view_through_conversion_NN = post-view). There is no pixel
-- name / pixel id dimension in this connector. This campaign's conversion reporting names "Sign up"
-- as both the conversion data source and the CPA optimisation source, so the slots that populate are
-- sign-ups - BUT the TTD UI shows "Sign up +1", i.e. a SECOND source is attached, and Windsor cannot
-- tell us which slot is which. So:
--   * we sum ALL 12 slots per kind (a second tracker must never be silently dropped), and
--   * we carry `conv_slots` - the names of the slots that actually fired on the row - so the job can
--     print them and a second populated slot can be SPLIT OUT here the day it appears.
-- `conversion_touch_NN` (TOTAL pixel fires, mostly NOT ad-attributed) is deliberately unused - see
-- clients/client_vmch/sql/03_stg_ttd.sql. CAVEAT (from VMCH): TTD can export one tracker as a
-- DUPLICATE PAIR of columns; if `conv_slots` ever shows an adjacent pair, sum only the first of each.
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
      r'^[0-9]+_', '')) AS _tier
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
    WHEN _tier = 'TIER2-QUOTED'    THEN 'Tier 2 - quoted'
    WHEN _tier = 'TIER3-PROJECT'   THEN 'Tier 3 - project work'
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
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_01') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_02') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_04') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_12') AS FLOAT64), 0) ) AS post_view_conv,
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_01') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_02') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_04') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_12') AS FLOAT64), 0) ) AS post_click_conv,
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
  CASE _stage_code
    WHEN 'AWR'    THEN 'Awareness'
    WHEN 'CONSID' THEN 'Consideration'
    WHEN 'CONV'   THEN 'Conversion'
    ELSE 'Unclassified'   -- LOUD on purpose: the job WARNs and the chip appears. Never default this.
  END                                                            AS funnel_stage
FROM parsed
