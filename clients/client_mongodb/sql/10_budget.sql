-- budget: MongoDB media-plan budget per programme. Source of truth is the VERSION-CONTROLLED
-- committed CSV targets/budget.csv, loaded to client_mongodb.seed_budget by seed_static.py
-- (the cross-client "targets in BQ from a committed CSV" standard). Thin alias view so the job
-- is unchanged. To change: edit targets/budget.csv -> seed_static.py -> export FORCE_REBUILD=1.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.budget` AS
SELECT PROGRAMME_LABEL, TRADEDESK_CODE, GROSS_BUDGET_USD, NET_BUDGET_USD, START_DATE, END_DATE, EST_CPC
FROM `bidbrain-analytics.client_mongodb.seed_budget`;
