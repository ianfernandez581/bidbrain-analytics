-- Schneider Electric — SEED: KPI targets per internal campaign. Editable. internal_campaign_id
-- × kpi × target_value (nullable). The dashboard shows KPI-vs-target progress only where a
-- target exists; campaigns with no target row simply omit the progress bar.
--
-- TODO complete from media plans — only the brief-stated targets are seeded; leave the rest out
-- (or add with NULL target_value) rather than inventing numbers:
--   * EBA 300 opt-in MQLs → now on 'eba' (EcoStruxure Building Activate). RESOLVED 2026-06-16:
--     EBA was split into its own campaign-map row (job 2079, distinct from eae/Automation Expert);
--     the 300 opt-in MQL target — sourced from the EBA brief, not EAE — moved here off 'eae'.
--   * EcoConsult: +100% traffic, 25 SQLs, 20 consults, ≥40% webinar attendance.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_targets` AS
SELECT * FROM UNNEST([
  STRUCT(
    'eba' AS internal_campaign_id, 'opt_in_mqls' AS kpi, 300.0 AS target_value),
  STRUCT('ecoconsult', 'traffic_uplift_pct',      100.0),
  STRUCT('ecoconsult', 'sqls',                     25.0),
  STRUCT('ecoconsult', 'consults',                 20.0),
  STRUCT('ecoconsult', 'webinar_attendance_pct',   40.0)
]);
