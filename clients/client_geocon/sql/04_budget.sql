-- 04_budget: per-DEVELOPMENT media-plan budget / flight window. Source of truth is the
-- VERSION-CONTROLLED committed CSV targets/budget.csv, loaded to client_geocon.seed_budget
-- by seed_static.py. To change: edit budget.csv -> seed_static.py -> export FORCE_REBUILD=1.
--
-- KEYED BY DEVELOPMENT since 2026-08-24 (the column was `campaign_key` holding the literal
-- 'GATEWAY'; it is now `property_key` holding the same key seed_property_map uses, so the join to
-- a row's `property` is direct and a new development is a CSV line rather than a code change).
--
-- `measurable_budget_aud` is the slice of the committed budget this pipeline can ever report
-- delivery against. For Northbourne that is A$188,500 of A$205,600: the SEO retainer (A$9,600) has
-- no ad server and the Google Search management fee (A$7,500) is an agency fee, not media. Pacing
-- against the full A$205,600 would read permanently under-pace by construction, so the dashboard
-- paces on this figure and shows the committed total beside it. For a development whose whole
-- budget is measurable the two are simply equal.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.budget` AS
SELECT
  property_key,
  CAST(budget_aud AS FLOAT64)            AS budget_aud,
  CAST(measurable_budget_aud AS FLOAT64) AS measurable_budget_aud,
  flight_start,
  flight_end
FROM `bidbrain-analytics.client_geocon.seed_budget`
