-- Schneider Electric — SEED: plan flighting (intended spend weight per period). Editable.
-- internal_campaign_id × period (YYYY-MM) × weight_pct. The dashboard compares actual monthly
-- spend against these weights (pacing-vs-plan); where a campaign has no flighting rows, it
-- shows pacing-vs-elapsed only. Flighting/cannibalisation is a brief concern — overlapping
-- flights are surfaced on the Portfolio Gantt regardless.
--
-- TODO complete from media plans. Only EcoConsult has brief-stated weights (35/45/10/10); the
-- PERIOD MONTHS are unknown — fill the YYYY-MM once the plan is to hand (NULL today). MCSeT is
-- "staged" and 2306 (ai_lc) is "flighted" per the brief, but without weights/months — add rows
-- when confirmed. Do NOT invent weights/months beyond the brief.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_plan_flighting` AS
SELECT * FROM UNNEST([
  STRUCT(
    'ecoconsult' AS internal_campaign_id, CAST(NULL AS STRING) AS period, 35.0 AS weight_pct),
  STRUCT('ecoconsult', CAST(NULL AS STRING), 45.0),
  STRUCT('ecoconsult', CAST(NULL AS STRING), 10.0),
  STRUCT('ecoconsult', CAST(NULL AS STRING), 10.0)
]);
