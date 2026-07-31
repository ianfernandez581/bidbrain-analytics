-- 01_stg_ttd: filter raw_windsor.perf_the_trade_desk to the Caltex advertiser, daily x campaign x
-- ad group x creative x ad_format grain. This is the client's slice + the tactic/market parse + the
-- per-row funnel_stage classification. The raw layer IS raw_windsor.perf_the_trade_desk (Windsor TTD
-- connector, self-refreshing via the windsor-tradedesk-ingest job) -- NOT Snowflake.
--
-- ADVERTISER FILTER: The Trade Desk advertiser id `0lw3hp6` (the id in the TTD platform URL,
-- desk.thetradedesk.com/...advertiser/0lw3hp6). The advertiser-name fallback catches the row if
-- Windsor ever reports a differently-cased/spaced id (belt & braces; VMCH filters by name alone).
--
-- TACTIC / MARKET: ad group names follow "Tactic | Market", e.g. 'Display Standard | QLD+WA',
-- 'AI Contextual | QLD+WA', 'Attention-Optimised | QLD+WA' -> tactic='Display Standard',
-- market='QLD+WA'. An un-piped ad group falls back to market='All markets'.
--
-- FUNNEL STAGE (mixed awareness + consideration campaign; ASSUMPTION, revisit with the media plan):
--   Display Standard      -> Awareness      (broad-reach display: cheap, wide exposure)
--   AI Contextual         -> Consideration  (contextually-relevant placements = in-market moments)
--   Attention-Optimised   -> Consideration  (paying for engaged attention, judged on CTR quality)
-- Anything new/unmatched defaults to Awareness so a fresh ad group is never dropped.
--
-- ATTRIBUTED CONVERSIONS: Windsor's `conversions` column is a double-encoded JSON string holding
-- TTD's anonymous numbered slots (view_through_conversion_NN = post-view, click_conversion_NN =
-- post-click). conversion_touch_NN (TOTAL pixel fires, mostly NOT ad-attributed) is deliberately NOT
-- used -- see client_vmch/sql/03_stg_ttd.sql. We sum ALL 12 slots per kind because Caltex's pixel
-- layout is unknown until pixels fire. CAVEAT (from VMCH): TTD can export one tracker as a DUPLICATE
-- PAIR of columns -- once Caltex pixels fire, verify the slot layout and, if pairs duplicate, sum
-- only the first column of each pair (the VMCH {01,03,05} pattern).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_caltex.stg_ttd` AS
WITH base AS (
  SELECT *, PARSE_JSON(JSON_VALUE(conversions)) AS _conv
  FROM `bidbrain-analytics.raw_windsor.perf_the_trade_desk`
  WHERE advertiser_id = '0lw3hp6'
     OR LOWER(TRIM(advertiser_name)) LIKE 'caltex%'
)
SELECT
  metric_date                                                    AS date,
  campaign_id,
  TRIM(campaign_name)                                            AS campaign_name,
  ad_group_id,
  TRIM(ad_group_name)                                            AS ad_group_name,
  TRIM(SPLIT(ad_group_name, '|')[SAFE_OFFSET(0)])                AS tactic,
  COALESCE(TRIM(SPLIT(ad_group_name, '|')[SAFE_OFFSET(1)]), 'All markets') AS market,
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
  -- FUNNEL STAGE: all three ad groups are set to AWARENESS in The Trade Desk (client-confirmed
  -- 2026-07-31). An earlier version INFERRED the stage from the ad-group name and wrongly tagged
  -- 'AI Contextual' and 'Attention-Optimised' as Consideration - that was our inference, never TTD's
  -- setting, and it mislabelled the funnel-stage table.
  --
  -- Why it is hard-coded rather than read from the feed: TTD's ad-group "Funnel location" column is
  -- NOT exposed by the Windsor connector (verified against raw_windsor.windsor_fields - the only
  -- funnel-ish field is `campaign_objective`, which is CAMPAIGN-level and so cannot distinguish
  -- ad groups once a consideration phase is added inside the same campaign).
  --
  -- TO ADD A CONSIDERATION PHASE LATER: change that ad group's line below. The mapping is keyed on
  -- the tactic (the part before the '|' in the ad-group name) so a new market inherits it for free.
  CASE TRIM(SPLIT(ad_group_name, '|')[SAFE_OFFSET(0)])
    WHEN 'Display Standard'    THEN 'Awareness'
    WHEN 'AI Contextual'       THEN 'Awareness'
    WHEN 'Attention-Optimised' THEN 'Awareness'
    ELSE 'Awareness'                       -- a brand-new ad group defaults to Awareness, never guessed
  END AS funnel_stage
FROM base
