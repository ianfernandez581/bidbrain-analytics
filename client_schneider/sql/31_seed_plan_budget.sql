-- Schneider Electric — SEED: plan budget per internal campaign (AUD). Editable in-repo.
-- budget_basis ∈ {'incl_fees','ex_fees'} so the dashboard can label whether spend is being
-- compared like-for-like (it shows the basis next to each card so spend isn't misread).
-- flight_start / flight_end drive pacing-vs-elapsed and the flight-overlap Gantt; where NULL,
-- the dashboard falls back to the OBSERVED delivery window (ad_campaigns min/max date).
--
-- TODO complete from media plans — only the brief-stated numbers are filled; the rest are NULL:
--   * water_env  95,000  incl_fees   (brief)
--   * ai_lc      480,600 ex_fees     (= the 2306 approved channel split total — see seed_channel_split)
--   * heavy      87,500  ex_fees     (brief "Heavy"; not yet matched to a delivery campaign — TODO)
--   * flight_start / flight_end: TODO from the plan (all NULL today → delivery window is used).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_plan_budget` AS
SELECT * FROM UNNEST([
  STRUCT(
    'water_env' AS internal_campaign_id, 95000.0 AS budget_aud, 'incl_fees' AS budget_basis,
    CAST(NULL AS DATE) AS flight_start, CAST(NULL AS DATE) AS flight_end),
  STRUCT('ai_lc',        480600.0, 'ex_fees',  NULL, NULL),
  STRUCT('heavy',         87500.0, 'ex_fees',  NULL, NULL),
  STRUCT('eae',             CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('aveva',           CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('csp',             CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('ent_it',          CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('ind_edge',        CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('mcset',           CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('ia_services',     CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('impact_maker',    CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('iof',             CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('mea_seg',         CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('power_products',  CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('digital_bldg',    CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('digital_power',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('ecocare',         CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('modernisation',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('active_kpx',      CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('pac_hybrid_it',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL)
]);
