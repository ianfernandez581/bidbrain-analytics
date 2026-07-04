-- 04_budget: Next Smile Australia media-plan budget / flight window. Source of truth is the
-- VERSION-CONTROLLED committed CSV targets/budget.csv, loaded to client_nextsmile.seed_budget
-- by seed_static.py. To change: edit budget.csv -> seed_static.py -> export FORCE_REBUILD=1.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_nextsmile.budget` AS
SELECT
  campaign_key,
  CAST(budget_aud AS FLOAT64) AS budget_aud,
  flight_start,
  flight_end
FROM `bidbrain-analytics.client_nextsmile.seed_budget`