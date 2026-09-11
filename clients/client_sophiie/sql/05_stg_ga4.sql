-- 05_stg_ga4: the Sophiie slice of the SHARED raw_windsor.perf_ga4 table (Google Analytics 4,
-- session-acquisition grain: date x channel group x source/medium x campaign). Property
-- `468621509`, the sophiie.ai GA4 property, connected via the Windsor GA4 connector.
--
-- THIS IS WHOLE-SITE CONTEXT, NOT CAMPAIGN ATTRIBUTION, and nothing downstream may present it as
-- attribution. The paid lane here is ONE Trade Desk DISPLAY PROSPECTING campaign
-- (SOPHIIE_2026-Q3_TTD_AU_DISPLAY_PROSPECTING). Display is upper-funnel and GA4's last-click model
-- badly understates it - the VMCH precedent in md/AGENTS.md, where display's post-view impact was
-- real while GA4 credited almost nothing to a "Display" session. The numbers here answer "what is
-- happening on the website", never "did the ads work".
--
-- MEASURED, NOT ASSUMED. Verified 2026-09-11 across the flight window 2026-09-04..09-10:
--   * GA4 records 1,071 Display sessions and ZERO conversions attributed to Display.
--   * The Trade Desk claims 518 attributed conversions over the same days, 86% of them POST-VIEW.
-- Those two figures are an order of magnitude apart and BOTH are correct for what they measure: a
-- post-view display conversion is invisible to a last-click session model by construction. So GA4
-- must NEVER be rendered as confirming or contradicting the ad platform's conversion count, and no
-- surface may compute a "discrepancy", a "true" conversion figure or a reconciliation between them.
--
-- WHY THE LANE EXISTS AT ALL: the property carries ~18 months of history (first day 2024-12-12),
-- which is the entire point - it makes a PRE-FLIGHT vs IN-FLIGHT baseline comparison possible.
-- Site-wide sessions, users and engagement BEFORE 2026-09-03 against the same measures during the
-- flight is a directional read on whether an upper-funnel display buy is moving site demand. That
-- comparison needs the deep history, not the campaign dimension.
--
-- THE JUNK-ROW GUARD IS NOT DEFENSIVE PROGRAMMING, IT IS A REAL INCIDENT. On 2026-09-10/11 the
-- Windsor API returned its PLAN-LIMIT ERROR STRING AS DATA - rows whose account_name / property_id
-- literally began "Uh-oh" - and the loader wrote them into the mirror like any other row. Those
-- rows are deleted now, but the vendor can do it again at any time and the failure is SILENT: the
-- string lands in a dimension, the metrics are zero or garbage, and the dashboard renders a
-- nonsense channel group rather than erroring. The predicate is cheap insurance, so it stays.
-- Keep it on BOTH columns: the error text has appeared in each.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_sophiie.stg_ga4` AS
SELECT
  metric_date                                              AS date,
  -- Windsor's GA4 dimensions are REQUIRED in the mirror schema, but GA4 itself emits '(not set)'
  -- and the loader has shipped NULLs before, so each dimension is coalesced to a stable label.
  -- 'Unassigned' is GA4's own name for traffic it cannot bucket - use its wording, do not invent one.
  COALESCE(session_default_channel_group, 'Unassigned')    AS channel_group,
  COALESCE(session_source_medium, '(not set)')             AS source_medium,
  COALESCE(session_campaign_name, '(not set)')             AS campaign,
  SUM(sessions)                                            AS sessions,
  SUM(engaged_sessions)                                    AS engaged_sessions,
  SUM(total_users)                                         AS users,
  SUM(new_users)                                           AS new_users,
  SUM(screen_page_views)                                   AS pageviews,
  -- NUMERIC in the mirror. Cast to FLOAT64 here so every consumer gets one type: a NUMERIC leaking
  -- downstream serialises as a string through the BigQuery client and quietly breaks arithmetic in
  -- job/main.py. Seconds, not minutes - divide at render time, never in the warehouse.
  CAST(SUM(user_engagement_duration) AS FLOAT64)           AS engagement_sec,
  -- GA4 key events. FRACTIONAL by design (GA4 can attribute a part of a key event), which is why it
  -- is NUMERIC upstream and FLOAT64 here, never an INT64. This is the SITE's key-event count and has
  -- no relationship to The Trade Desk's Try free click figure - see the header.
  CAST(SUM(conversions) AS FLOAT64)                        AS conversions
FROM `bidbrain-analytics.raw_windsor.perf_ga4`
WHERE property_id = '468621509'
  -- See the header: Windsor has returned its plan-limit error text as a row value.
  AND NOT (LOWER(account_name) LIKE 'uh-oh%' OR LOWER(property_id) LIKE 'uh-oh%')
GROUP BY date, channel_group, source_medium, campaign
