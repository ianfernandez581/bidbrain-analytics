-- HireRight - media-plan targets. A thin view over the committed-CSV seed table
-- `seed_media_plan` (targets/media_plan.csv -> seed_static.py), per the repo-wide
-- committed-CSV->BQ standard.
--
-- ORDER OF OPERATIONS: seed_static.py MUST run before create_views.py the first time.
-- BigQuery validates a view's query when it is created, so this file fails with
-- "Not found: Table ... seed_media_plan" if the seed has never been loaded. Both
-- deploy scripts do the seed first; if you hit that error, that is the reason.
--
-- EVERY TARGET COLUMN IS NULLABLE AND NULL IS MEANINGFUL: it means "the plan does not
-- commit to this metric", which is NOT a target of zero. Consumers must branch on NULL
-- and omit the metric, never render a 0% attainment against it - a red miss on a KPI
-- the client never bought is worse than showing nothing (the client_caltex lesson:
-- targets we derived ourselves have to be labelled or dropped).
--
-- The CSV is currently all-blank (HireRight has no signed plan in this repo), so
-- `pacing.has_targets` is FALSE and the dashboard hides its pacing section entirely.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.targets` AS
SELECT
  LOWER(TRIM(PLATFORM))                    AS platform,
  NULLIF(TRIM(COALESCE(LINE_ITEM, '')), '') AS line_item,
  FLIGHT_START                             AS flight_start,
  FLIGHT_END                               AS flight_end,
  BUDGET_USD                               AS budget_usd,
  IMP_TARGET                               AS imp_target,
  CLICK_TARGET                             AS click_target,
  LEAD_TARGET                              AS lead_target,
  CTR_TARGET                               AS ctr_target,
  CPM_TARGET_USD                           AS cpm_target_usd,
  CPC_TARGET_USD                           AS cpc_target_usd
FROM `bidbrain-analytics.client_hireright.seed_media_plan`
WHERE PLATFORM IS NOT NULL AND TRIM(PLATFORM) <> '';
