-- 03_targets: Next Smile Australia flight targets + pacing. Source of truth is the VERSION-CONTROLLED
-- committed CSV targets/targets.csv, loaded to client_nextsmile.seed_targets by seed_static.py.
-- This view is a thin pass-through; to change targets: edit the CSV -> seed_static.py ->
-- export FORCE_REBUILD=1 (a seed change is invisible to the freshness gate).
-- value stays STRING (the CSV holds both numbers and dates); job/main.py + the UI parse as needed.
-- Rows marked status='PENDING' are placeholders needing client sign-off; the UI renders them with a
-- "target pending confirmation" marker so nobody mistakes an assumption for an agreed KPI.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_nextsmile.targets` AS
SELECT
  key,
  value,
  status
FROM `bidbrain-analytics.client_nextsmile.seed_targets`