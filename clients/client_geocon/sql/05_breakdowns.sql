-- 05_breakdowns: Geocon-only Meta breakdown facts — audience (age x gender) + placement.
-- Source: raw_windsor.geocon_meta_breakdown, an ISOLATED geocon-only table populated by
-- clients/client_geocon/ingest/meta_breakdown_pull.py (NOT the shared perf_meta). One row per
-- (date x campaign x breakdown x seg1 x seg2); the dashboard date-filters and rolls up client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.breakdowns` AS
SELECT date, campaign, breakdown, seg1, seg2,
       impressions, reach, clicks, link_clicks, spend, leads,
       -- PROPERTY, derived exactly as in 01_stg_meta (keep the two regexes IDENTICAL or the
       -- audience/placement charts will disagree with the KPIs above them). Without this the
       -- breakdown charts could not be split, so a Northbourne view would have shown Gateway
       -- Braddon's audience mix under a Northbourne heading.
       CASE
         WHEN REGEXP_CONTAINS(campaign, r'(?i)north\s*bourne|nbg') THEN 'Northbourne Gateway'
         ELSE 'Gateway Braddon'
       END AS property
FROM `bidbrain-analytics.raw_windsor.geocon_meta_breakdown`;
