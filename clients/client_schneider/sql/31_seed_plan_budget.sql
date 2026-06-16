-- Schneider Electric — SEED: plan budget per internal campaign (AUD). Editable in-repo.
-- budget_basis ∈ {'incl_fees','ex_fees'} so the dashboard can label whether spend is being
-- compared like-for-like (it shows the basis next to each card so spend isn't misread).
-- flight_start / flight_end drive pacing-vs-elapsed and the flight-overlap Gantt; where NULL,
-- the dashboard falls back to the OBSERVED delivery window (ad_campaigns min/max date).
--
-- Budgets are the media-plan brief TOP-LINE totals (regional/channel splits live in
-- seed_channel_split, not here), normalised to integer AUD, ex-fees unless the brief states
-- incl-fees. Seeded from the briefs 2026-06-04:
--   * water_env   95,000 incl_fees  (brief; incl fees)
--   * ai_lc      480,600 ex_fees    (= the 2306 approved channel split total — see seed_channel_split)
--   * heavy       87,500 ex_fees    (brief "Heavy" 100,000 incl / 87,500 ex → store ex-fees per the
--                                     default basis; not yet matched to a delivery campaign)
--   * ent_it     100,000 ex_fees    (Enterprise IT, brief job 1958)
--   * csp         82,355 ex_fees    (C&SP Relationship Marketing, brief job 1957)
--   * mcset       70,000 ex_fees    (MCSeT + EvoPacT, brief job 1130 — DISTINCT from water_env, also 1130;
--                                     keyed by internal id, not job number, so no collision)
--   * ind_edge    49,596 ex_fees    (Industrial Edge Wave 3 Prefab, brief job 1839; the 40/60 digital/CS
--                                     split is a channel concern, not reflected in this top-line total)
--   * ecoconsult  30,000 ex_fees    (EcoConsult, brief job 2279)
--   * aveva       15,400 ex_fees    (AVEVA — no warehouse delivery yet; shows budget, zero spend)
--   * eae         10,900 ex_fees    (EcoStruxure Automation Expert; see IDENTITY NOTE below)
--   * ia_services  8,750 ex_fees    (IA Services)
-- Still NULL — no brief budget supplied: impact_maker, iof, mea_seg, power_products, digital_bldg,
-- digital_power, ecocare, modernisation, active_kpx, pac_hybrid_it.
--
-- IDENTITY NOTE (RESOLVED 2026-06-16): 'eae' = EcoStruxure Automation Expert (job 1974, EAE brief
-- budget 10,900 ex-fees). EBA = EcoStruxure Building Activate (job 2079) is now its OWN campaign-map
-- row (delivery 'SE_EBA_Activate_AWR_June4'), with the 300 opt-in MQL target moved onto it (see
-- seed_targets). EBA's 20,000 ex-fees budget (from the EBA brief) is therefore seeded here on 'eba'.
-- flight_start / flight_end: seeded from the activation briefs ("Campaign Dates" field) for the
-- currently-active campaigns where the brief gives a usable window —
--   * water_env   2026-03-01 → 2026-12-31  (brief: Pillar 1 Mar–Jun, Pillar 2 Mar–Dec, Pillar 3 Jul–Sep → outer span)
--   * ent_it      2026-04-15 → 2026-09-30  (brief: "April – September 2026, 3rd week April start")
--   * ia_services 2026-03-09 → 2026-06-01  (brief: "9 March – 1 June"; matches observed delivery)
-- Still NULL (brief window not usable — Portfolio "vs plan to date" view shows "plan dates not set"):
--   * ai_lc — brief defers to the media-plan PPT (slide 29) and says "need to add dates"; no year given.
--   * eae   — brief says "end April to end June" but the matched Automation Expert delivery ran
--             Dec 2025 → May 2026 (see IDENTITY NOTE) — conflicting, left for confirmation.
-- Where NULL the dashboard falls back to the observed delivery window for the Gantt only.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_plan_budget` AS
SELECT * FROM UNNEST([
  STRUCT(
    'water_env' AS internal_campaign_id, 95000.0 AS budget_aud, 'incl_fees' AS budget_basis,
    DATE '2026-03-01' AS flight_start, DATE '2026-12-31' AS flight_end),
  STRUCT('ai_lc',        480600.0, 'ex_fees',  NULL, NULL),
  STRUCT('heavy',         87500.0, 'ex_fees',  NULL, NULL),
  STRUCT('eae',           10900.0,  'ex_fees',  NULL, NULL),
  STRUCT('eba',           20000.0,  'ex_fees',  NULL, NULL),
  STRUCT('aveva',         15400.0,  'ex_fees',  NULL, NULL),
  STRUCT('csp',           82355.0,  'ex_fees',  NULL, NULL),
  STRUCT('ent_it',        100000.0, 'ex_fees',  DATE '2026-04-15', DATE '2026-09-30'),
  STRUCT('ind_edge',      49596.0,  'ex_fees',  NULL, NULL),
  STRUCT('mcset',         70000.0,  'ex_fees',  NULL, NULL),
  STRUCT('ia_services',   8750.0,   'ex_fees',  DATE '2026-03-09', DATE '2026-06-01'),
  STRUCT('impact_maker',    CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('iof',             CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('mea_seg',         CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('power_products',  CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('digital_bldg',    CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('digital_power',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('ecocare',         CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('modernisation',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('active_kpx',      CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  STRUCT('pac_hybrid_it',   CAST(NULL AS FLOAT64), CAST(NULL AS STRING), NULL, NULL),
  -- ecoconsult was absent from this seed (present in seed_campaign_map/targets/flighting); add it:
  STRUCT('ecoconsult',    30000.0,  'ex_fees',  NULL, NULL)
]);
