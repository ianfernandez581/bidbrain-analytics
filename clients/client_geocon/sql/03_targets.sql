-- 03_targets: per-DEVELOPMENT flight targets + pacing. Source of truth is the VERSION-CONTROLLED
-- committed CSV targets/targets.csv, loaded to client_geocon.seed_targets by seed_static.py.
-- This view is a thin pass-through; to change targets: edit the CSV -> seed_static.py ->
-- export FORCE_REBUILD=1 (a seed change is invisible to the freshness gate).
-- value stays STRING (the CSV holds both numbers and dates); job/main.py + the UI parse as needed.
-- Rows marked status='PENDING' are placeholders needing client sign-off; the UI renders them with a
-- "target pending confirmation" marker so nobody mistakes an assumption for an agreed KPI. A
-- PENDING row may carry an EMPTY value (Northbourne's lead targets do -- the signed media plan
-- commits no lead number), which reads through as NULL and renders as "-", never as zero.
--
-- KEYED BY DEVELOPMENT since 2026-08-24. It used to be a flat key/value set, which was correct
-- while Gateway Braddon was the only development; the moment Northbourne Gateway arrived with its
-- own A$205,600 plan and 2026-08-13..10-31 flight, one shared set of targets would have paced each
-- development against the other's plan. Every key is now scoped by property_key.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.targets` AS
SELECT
  property_key,
  key,
  value,
  status
FROM `bidbrain-analytics.client_geocon.seed_targets`
