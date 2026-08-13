-- 06_geo: REAL delivery by Australian state, from the caltex-only geo table.
--
-- WHY THIS IS A SEPARATE LANE. Everywhere else on this dashboard "market" is parsed out of the
-- ad-group NAME ("Tactic | Market"), so every row reads 'QLD+WA' - one lump that can never show a
-- third state no matter where the ads actually served. Probing Windsor's TTD `region` field on
-- 2026-08-12 showed the campaign IS delivering into SOUTH AUSTRALIA while the ad group still says
-- QLD+WA. This view is the honest geo answer; the ad-group `market` stays as the BUYING label.
--
-- SOURCE is raw_windsor.caltex_ttd_geo, an ISOLATED caltex-only table written by
-- clients/client_caltex/ingest/ttd_geo_pull.py. The shared perf_the_trade_desk deliberately does
-- NOT carry `region`: it multiplies the grain ~29x (measured 50 -> 1,462 rows for one seat over
-- three days) and that table feeds FIVE TTD clients. Same isolation as the geocon breakdown table.
--
-- RECONCILIATION (2026-08-12, whole flight 07-28..08-11): QLD 100,463 + WA 63,508 + SA 3,067 =
-- 167,038 impressions, EXACTLY the 167,038 in stg_ttd. Re-check this after any re-pull - a geo
-- split that does not sum to the headline is worse than no geo split at all.
--
-- NOT GATED: the pull is manual (like geocon's breakdowns), so this view can lag the main feed.
-- The dashboard labels it with its own max date rather than the campaign's.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_caltex.geo` AS
SELECT
  date,
  campaign,
  ad_group_name,
  region,
  -- NULL state = Windsor returned no region for that slice. Kept as an explicit bucket rather than
  -- dropped or folded into a real state, so the geo total always reconciles to the headline.
  COALESCE(state, 'Unattributed')                                  AS state,
  -- Short label for chips/axis. Anything outside the three known states keeps its full name.
  CASE state
    WHEN 'Queensland'      THEN 'QLD'
    WHEN 'Western Australia' THEN 'WA'
    WHEN 'South Australia' THEN 'SA'
    WHEN 'New South Wales' THEN 'NSW'
    WHEN 'Victoria'        THEN 'VIC'
    WHEN 'Tasmania'        THEN 'TAS'
    WHEN 'Northern Territory' THEN 'NT'
    WHEN 'Australian Capital Territory' THEN 'ACT'
    ELSE COALESCE(state, 'Unattributed')
  END                                                              AS state_code,
  impressions,
  clicks,
  spend
FROM `bidbrain-analytics.raw_windsor.caltex_ttd_geo`
