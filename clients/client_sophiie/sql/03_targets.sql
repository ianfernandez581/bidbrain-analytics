-- 03_targets: Sophiie AI flight targets + pacing. Source of truth is the VERSION-CONTROLLED
-- committed CSV targets/targets.csv, loaded to client_sophiie.seed_targets by seed_static.py.
-- This view is a thin pass-through; to change targets: edit the CSV -> seed_static.py ->
-- export FORCE_REBUILD=1 (a seed change is invisible to the freshness gate).
-- value stays STRING (the CSV holds both numbers and dates); job/main.py + the UI parse as needed.
--
-- STATUS is load-bearing, not decoration:
--   HARD    = committed in The Trade Desk / the signed plan. CPA A$150, CPC A$3.00, CTR 0.15% are
--             the campaign's own Primary / Secondary / Tertiary KPI targets, and the A$10,000
--             budget + 3 Sep - 3 Oct flight are the campaign's own settings.
--   DERIVED = OURS, inferred from those - CPM (= CPC x CTR x 1000 = A$4.50), the impression target
--             (budget / CPM) and the sign-up target (budget / CPA). The UI must LABEL these, or a
--             red delta accuses the campaign of missing a KPI nobody agreed to (the caltex rule).
--   PENDING = a placeholder awaiting client sign-off; the UI marks it "pending".
CREATE OR REPLACE VIEW `bidbrain-analytics.client_sophiie.targets` AS
SELECT
  key,
  value,
  status
FROM `bidbrain-analytics.client_sophiie.seed_targets`
