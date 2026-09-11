-- 06_stg_ga4_events: the Sophiie slice of raw_windsor.perf_ga4_events (GA4 event counts,
-- property x date x event_name). Property `468621509`, the sophiie.ai GA4 property - same scope as
-- 05_stg_ga4; see that header for the whole-site-context reasoning, the measured Display-vs-TTD
-- divergence and why the ~18 months of history is the point of this lane.
--
-- EVENTS CARRY NO CAMPAIGN, SOURCE OR CHANNEL DIMENSION - only the date and the event name. So an
-- event count here is SITE-WIDE and can never be split by traffic source, let alone attributed to
-- the Trade Desk buy. A "Try free" event on this feed is every Try free click on the site, from
-- every channel and from direct traffic, and it is NOT the same measure as The Trade Desk's
-- attributed Try free click figure. Nothing downstream may compare, reconcile or substitute one for
-- the other.
--
-- `is_key` is GA4's own key-event flag, aggregated with LOGICAL_OR rather than picked from a row:
-- the flag is a property of the EVENT, not of a day, but it is carried per row and the site owner
-- can toggle it at any time. LOGICAL_OR means "this was a key event on at least one day in range",
-- which keeps an event that was marked key partway through the history visible as such instead of
-- flickering by date. ANY_VALUE would be non-deterministic here, which is exactly the flicker.
--
-- NOTE the source table has property_id but NO account_name column (verified against the live
-- schema), so this view carries only the property-id half of the 05_stg_ga4 junk-row guard. If the
-- Windsor plan-limit error string ever lands in this table it will land in property_id, and the
-- scope filter below already rejects it - an equality test on the real id admits nothing else.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_sophiie.stg_ga4_events` AS
SELECT
  metric_date                          AS date,
  event_name                           AS event,
  -- COALESCE to FALSE, not NULL: the flag is NULLABLE upstream and an unflagged event is simply not
  -- a key event. A NULL here would make a downstream `WHERE is_key` silently drop rows it should
  -- have counted as FALSE, and BOOL NULL renders as an empty cell rather than a readable state.
  COALESCE(LOGICAL_OR(is_conversion_event), FALSE) AS is_key,
  SUM(event_count)                     AS count
FROM `bidbrain-analytics.raw_windsor.perf_ga4_events`
WHERE property_id = '468621509'
GROUP BY date, event
