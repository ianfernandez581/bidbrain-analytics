-- 05_breakdowns: Geocon-only Meta breakdown facts — audience (age x gender) + placement.
-- Source: raw_windsor.geocon_meta_breakdown, an ISOLATED geocon-only table populated by
-- clients/client_geocon/ingest/meta_breakdown_pull.py (NOT the shared perf_meta). One row per
-- (date x campaign x breakdown x seg1 x seg2); the dashboard date-filters and rolls up client-side.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.breakdowns` AS
WITH map AS (
  SELECT seq, property_key, LOWER(COALESCE(match_pattern, '')) AS pat
  FROM `bidbrain-analytics.client_geocon.seed_property_map`
),
base AS (SELECT * FROM `bidbrain-analytics.raw_windsor.geocon_meta_breakdown`),
camps AS (SELECT DISTINCT campaign AS cname FROM base),
camp_rank AS (
  SELECT c.cname, m.property_key,
         ROW_NUMBER() OVER (PARTITION BY c.cname ORDER BY m.seq) AS rn
  FROM camps c, map m
  WHERE m.pat = ''
     OR EXISTS (SELECT 1 FROM UNNEST(SPLIT(m.pat, '|')) tok
                 WHERE TRIM(tok) != '' AND STRPOS(LOWER(c.cname), TRIM(tok)) > 0)
),
camp_map AS (SELECT cname, property_key FROM camp_rank WHERE rn = 1)
SELECT b.date, b.campaign, b.breakdown, b.seg1, b.seg2,
       b.impressions, b.reach, b.clicks, b.link_clicks, b.spend, b.leads,
       -- PROPERTY from the SAME seed table 01_stg_meta joins, so the two can never drift. Without
       -- this the breakdown charts could not be split, and a Northbourne view would have shown
       -- Gateway Braddon's audience mix under a Northbourne heading.
       cm.property_key AS property
FROM base b
JOIN camp_map cm ON b.campaign = cm.cname;
