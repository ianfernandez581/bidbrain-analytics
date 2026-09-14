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
-- FUNNEL STAGE: STATED FROM THE TRADE DESK, NEVER INFERRED FROM THE NAME. The three original ad
-- groups are all set to Awareness in TTD (client-confirmed 2026-07-31). An earlier version of this
-- view INFERRED the stage from the ad-group name and wrongly tagged 'AI Contextual' and
-- 'Attention-Optimised' as Consideration - our inference, never TTD's setting. Do not repeat it.
-- Anything unmatched resolves to 'Unclassified', which is DELIBERATE AND LOUD - see below.
--
-- ATTRIBUTED CONVERSIONS: ONE COLUMN PER ACTION, NEVER A SUM OVER SLOTS (settled 2026-09-14).
-- Windsor exposes TTD conversions ONLY as anonymous numbered slots (view_through_conversion_NN =
-- post-view, click_conversion_NN = post-click) with NO pixel name or id anywhere in the connector,
-- so which slot is which action cannot be read from the feed. It is read off the campaign's
-- "Configure campaign reporting and attribution" screen and STATED here:
--   column 01 -> Landing Page Visit (4tyuvnj), cross-device concept PERSON      <- THE figure
--   column 02 -> Landing Page Visit (4tyuvnj), cross-device concept HOUSEHOLD
--   columns 03-12 -> unused today; see `unmapped_conv` below
--
-- *** COLUMNS 01 AND 02 ARE THE SAME CONVERSIONS TWICE. *** TTD reports one data source once per
-- cross-device concept - Person (Identity Alliance) and Household (Identity Alliance with
-- Household) - so adding them DOUBLE COUNTS. This view summed all 12 slots per kind until
-- 2026-09-14 and therefore published 161 post-view / 364 post-click against a true 77 / 181.
-- We take PERSON, the tighter identity resolution; Household is carried beside it as a diagnostic
-- and must NEVER be added in. Verified on the live mirror: Household >= Person in 197 of 198
-- rows, and the two are byte-identical in 190 of them - two independent trackers cannot track
-- that closely. Same finding, same connector, same day as clients/client_sophiie/sql/01_stg_ttd.sql.
--
-- WHAT COLUMN 01 ACTUALLY COUNTS (live since 2026-08-10): the campaign's conversion reporting
-- carries ONE tracking tag - the URL-scoped `Landing Page Visit` (`4tyuvnj`, TTD event type
-- "Site visit", rule contains business-solutions/starcard/caltex-starcard). So the number is
-- ad-attributed visits to the STAR CARD LANDING PAGE, not all site traffic and NOT sign-ups.
-- The sitewide `Universal Pixel - Default` tag (`8za7r9n`, ~429k hits/30d) is NOT attached and must
-- never be substituted -- it is ~150x this number and counts all traffic, ad-exposed or not.
--
-- *** SIGN-UPS: THE TAG FIRES (2026-09-14) BUT NOTHING REPORTS HERE YET. ***
-- Caltex put the universal pixel on the application domain on 2026-09-14, and the TTD pixel screen
-- confirms it worked - the months-long "pixel is absent from oa.starcard.com.au" blocker is GONE:
--   `y79jotv` "Form Submitted"      contains OnlineApplication/confirmation.as*  event Message business
--                                   2 hits/1d, 2/7d, 2/30d   <- THE SIGN-UP (completed application)
--   `7y9naeh` "StarCard Apply Click" contains oa.starcard.com.au/OnlineApplicat* event Purchase
--                                   6 hits/1d, 7/7d, 7/30d   <- reaching the application flow, NOT
--                                   a completed application
--
-- THREE THINGS TO GET RIGHT WHEN THESE ARRIVE, none of them obvious:
--  1. THE TWO TAGS OVERLAP AND MUST NEVER BE SUMMED. A confirmation URL like
--     oa.starcard.com.au/OnlineApplication/confirmation.aspx satisfies BOTH rules, so every Form
--     Submitted ALSO fires StarCard Apply Click - 7y9naeh's 7 hits INCLUDE y79jotv's 2. They are
--     also different event types (Purchase vs Message business), i.e. different actions. Map
--     `y79jotv` as the sign-up; `7y9naeh` is at best an upper-funnel "reached the application".
--  2. THOSE HIT COUNTS ARE TOTAL PIXEL FIRES ACROSS ALL TRAFFIC, NOT AD-ATTRIBUTED. They are the
--     same measure as `conversion_touch_NN`, which this repo deliberately never reports (see
--     client_vmch/sql/03_stg_ttd.sql). The ad-attributed figure will be <= 2 and may well be 0.
--  3. BOTH NEW TAGS SHOW **ACTIVE IDS 0** against Landing Page Visit's 1.3K. TTD attributes by
--     matching the converting user's id back to an impression or click, so with no matchable ids
--     there is nothing to attribute and the campaign can report 0 while the tag fires happily.
--     client_sophiie hit exactly this on the same connector the same day. CHASE THE 0 ACTIVE IDS
--     BEFORE READING A 0 AS A RESULT - a published 0 says "the campaign produced nothing" when the
--     truth may be "we cannot yet match who converted".
--
-- The remaining wiring step is the one that kept SITE VISITS dark for two weeks in August: the tag
-- must ALSO be attached to this campaign's conversion reporting. When it is, it arrives as a NEW
-- numbered slot (03, and 04 for its Household twin). `unmapped_conv` sums 03-12 and MUST be 0; the
-- export job WARNs by name the moment it is not. That warning is the signal to map the new column
-- to its own measure HERE (and mirror it in the status-dash check, in the same commit). A sign-up
-- must NEVER be folded into site visits, and slot numbering is NOT a stable key - attaching or
-- detaching a data source in TTD renumbers the columns.
-- `conversion_touch_NN` (TOTAL pixel fires, mostly NOT ad-attributed) stays deliberately unused --
-- see clients/client_vmch/sql/03_stg_ttd.sql.
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
  -- Viewability: TTD measures only a SAMPLE, so the rate is viewed/tracked (never
  -- viewed/impressions). Both are NULL until viewability measurement is enabled on the ad
  -- groups in TTD, and NULL must stay distinguishable from a real 0% downstream.
  sampled_viewed_impressions,
  sampled_tracked_impressions,
  -- POST-VIEW / POST-CLICK: column 01 only (Person). See the slot map above.
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_01') AS FLOAT64), 0) AS post_view_conv,
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_01') AS FLOAT64), 0) AS post_click_conv,
  -- Household twins of the two figures above. DIAGNOSTIC ONLY - never add these in.
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_02') AS FLOAT64), 0) AS post_view_conv_household,
  COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_02') AS FLOAT64), 0) AS post_click_conv_household,
  -- TRIPWIRE for a newly attached tracker (the pending Star Card sign-up tag). MUST be 0;
  -- the export job WARNs by ad group the moment it is not. Do NOT let a new action reach
  -- post_view_conv/post_click_conv by widening the sums above - map it to its own measure.
  ( COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_04') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.view_through_conversion_12') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_03') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_04') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_05') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_06') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_07') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_08') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_09') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_10') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_11') AS FLOAT64), 0)
  + COALESCE(SAFE_CAST(JSON_VALUE(_conv, '$.click_conversion_12') AS FLOAT64), 0) ) AS unmapped_conv,
  -- FUNNEL STAGE, keyed on the TACTIC (the part before the '|' in the ad-group name) so a new
  -- market inherits it for free. The three original ad groups are set to AWARENESS in The Trade
  -- Desk (client-confirmed 2026-07-31).
  --
  -- Why it is stated rather than read from the feed: TTD's ad-group "Funnel location" column is NOT
  -- exposed by the Windsor connector (verified against raw_windsor.windsor_fields - the only
  -- funnel-ish field is `campaign_objective`, which is CAMPAIGN-level and so cannot distinguish ad
  -- groups once a consideration phase is added inside the same campaign).
  --
  -- *** THE ELSE IS 'Unclassified' ON PURPOSE, AND IT USED TO BE 'Awareness'. *** A real-value ELSE
  -- turns a new or renamed ad group into SILENT MISATTRIBUTION instead of a visible question - the
  -- repo-wide rule in md/AGENTS.md, and it bit here: `Retargetting | QLD+WA+SA` went live
  -- 2026-08-22 and was absorbed into Awareness for three weeks (40,668 imps / A$276.70), which a
  -- retargeting line definitionally is not. It now reports as Unclassified, the export job WARNs by
  -- ad-group name, and the dashboard shows the row - loud, not wrong.
  --
  -- TO CLASSIFY AN AD GROUP: add its tactic below, using the Funnel location THE TRADE DESK has set
  -- for it. Do NOT infer it from the word "Retargetting" - that is exactly the mistake above.
  CASE TRIM(SPLIT(ad_group_name, '|')[SAFE_OFFSET(0)])
    WHEN 'Display Standard'    THEN 'Awareness'
    WHEN 'AI Contextual'       THEN 'Awareness'
    WHEN 'Attention-Optimised' THEN 'Awareness'
    -- 'Retargetting' (the client's spelling) is deliberately NOT mapped - its TTD Funnel location
    -- has not been confirmed. One WHEN line here closes it.
    ELSE 'Unclassified'
  END AS funnel_stage
FROM base
