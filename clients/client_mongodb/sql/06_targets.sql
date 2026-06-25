-- targets: MongoDB CS lead targets per programme x market. Source of truth is the
-- VERSION-CONTROLLED committed CSV targets/targets.csv, loaded to client_mongodb.seed_targets
-- by seed_static.py (the cross-client "targets in BQ from a committed CSV" standard). This view
-- is a thin alias so the rest of the pipeline (job + targets_by_programme) is unchanged.
-- To change targets: edit targets/targets.csv -> seed_static.py -> export FORCE_REBUILD=1.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.targets` AS
SELECT PROGRAMME_LABEL, MARKET, TARGET_LEADS, DELIVERED_LEADS_SNAPSHOT, CPL
FROM `bidbrain-analytics.client_mongodb.seed_targets`;
