-- LQAIDC content syndication — delivered vs target, per vendor x region.
--
-- Targets are the PANGEA allocation reworked 2026-07-31 (ANZ 68 / India 235 / MEA 18 / SAM 79 = 400
-- at A$60 CPL = A$24,000), seeded from data/cs_targets.csv. Source: the media plan workbook's
-- "CSVendor Costs & Lead Avails" tab.
--
-- FULL OUTER JOIN on purpose, and both sides matter:
--   * a seeded region with NO delivery must still render (0 of 235 is the single most important
--     number on this card — dropping the row would hide the biggest shortfall);
--   * a region DELIVERING with no seeded target must also render, or the rows stop summing to the
--     headline lead count. It shows a NULL target rather than a zero, so the dashboard can say
--     "no target" instead of implying the delivery was unplanned.
--
-- PACE IS NOT COMPUTED HERE. It depends on today's date and on the flight window, and the repo has
-- already been bitten by a target-to-date that steps by a whole period (the "weekly target against
-- continuous time" rule). The dashboard prorates against the seeded flight; this view stays a
-- straight delivered-vs-total-target fact.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.cs_pacing` AS
WITH delivered AS (
  SELECT vendor, region, SUM(leads) AS leads, MIN(metric_date) AS first_lead, MAX(metric_date) AS last_lead
  FROM `bidbrain-analytics.client_schneiderlqai.stg_salesforce`
  GROUP BY vendor, region
),
target AS (
  SELECT vendor, region, lead_target, cpl_aud, cost_aud
  FROM `bidbrain-analytics.client_schneiderlqai.seed_cs_targets`
)
SELECT
  COALESCE(d.vendor, t.vendor)                 AS vendor,
  COALESCE(d.region, t.region)                 AS region,
  COALESCE(d.leads, 0)                         AS leads,
  t.lead_target,
  t.cpl_aud,
  t.cost_aud,
  d.first_lead,
  d.last_lead
FROM delivered d
FULL OUTER JOIN target t
  ON t.vendor = d.vendor AND t.region = d.region;
