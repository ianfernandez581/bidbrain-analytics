-- 05_breakdowns: Geocon-only Meta breakdown facts — audience (age x gender) + placement.
-- Source: raw_windsor.geocon_meta_breakdown, an ISOLATED geocon-only table populated by
-- clients/client_geocon/ingest/meta_breakdown_pull.py (NOT the shared perf_meta). One row per
-- (date x campaign x breakdown x seg1 x seg2); the dashboard date-filters and rolls up client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.breakdowns` AS
SELECT date, campaign, breakdown, seg1, seg2,
       impressions, reach, clicks, link_clicks, spend, leads
FROM `bidbrain-analytics.raw_windsor.geocon_meta_breakdown`;
