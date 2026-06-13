-- Schneider Electric — SEED: campaign map (the human bridge between the media-plan campaigns
-- and the raw platform campaign names). One row per internal campaign. Editable in-repo as a
-- STRUCT array. The dashboard joins each delivering platform campaign to a row by testing
-- whether the platform CAMPAIGN_NAME CONTAINS any of the '|'-separated match_pattern tokens
-- (case-insensitive); unmatched delivery falls back to display '(unmapped)' so nothing breaks.
--
-- TODO complete from media plans:
--  * brief_job_no holds the BRIEF's job number ('—' where the brief gives none). It is NOT the
--    platform PO code — those are intentionally NOT reconciled here (that's a human task); the
--    match_pattern is the only bridge. (e.g. csp brief 1957 ↔ platform PO 1608.)
--  * Rows tagged "[delivery]" were inferred from observed platform campaigns, not the brief —
--    confirm display/objective/region against the plan.
--  * 'aveva' has NO delivery in the warehouse yet (no platform campaign matches 'AVEVA') — TODO
--    confirm it launched / its naming. Until then it shows budget/targets but zero delivery.
--  * objective_type ∈ {Awareness, LeadGen, ABM, Event, Awareness→RT}. primary_kpi is free text.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_campaign_map` AS
SELECT * FROM UNNEST([
  STRUCT(
    'eae' AS internal_campaign_id, 'EcoStruxure Automation Expert' AS display_name,
    '—' AS brief_job_no, 'LeadGen' AS objective_type, 'Opt-in MQLs' AS primary_kpi,
    CAST(NULL AS STRING) AS pillar, 'ANZ' AS primary_region,
    'Ecostructure_Automation_Expert|Automation_Expert|Automation Expert' AS match_pattern),
  STRUCT('aveva','AVEVA','—','LeadGen','Opt-in MQLs',NULL,'ANZ','AVEVA'),
  STRUCT('ai_lc','AI & Liquid Cooling','2306','Awareness','Top-funnel engagement',NULL,'multi','AI in DC|LQAIDC|AI in DC '),
  STRUCT('csp','C&SP Relationship Marketing','1957','ABM','Brand preference & opps',NULL,'multi','C&SP'),
  STRUCT('ent_it','Enterprise IT Expansion','1958','ABM','Hand-raisers + MQLs',NULL,'multi','EntIT'),
  STRUCT('water_env','Water & Environment','1130','Awareness','Reach / Clicks / LP lands','3 pillars','ANZ','WaterEnv'),
  STRUCT('ind_edge','Industrial Edge / Prefab','1839','LeadGen','Qualified leads / CPL / CVR',NULL,'Pacific','Industrial Edge'),
  STRUCT('mcset','MCSeT + EvoPacT','1130','Event','Roadshow registrations',NULL,'ANZ','Cooling Solutions'),
  STRUCT('ia_services','IA Services','—','Awareness→RT','Reach / freq, VCR',NULL,'ANZ','AI Services'),
  STRUCT('impact_maker','Impact Maker','1914','Awareness','Reach / engagement',NULL,'ANZ','Impact_Maker|Imapct_Maker'),
  STRUCT('iof','Industries of the Future','1899','Awareness','Engagement',NULL,'multi','IOF|Industries of the Future'),
  STRUCT('mea_seg','MEA Segment Program','2353','ABM','TAL engagement','MEA','MEA','2353|MEA Segment'),
  -- [delivery] inferred from observed platform campaigns — confirm against the plan:
  STRUCT('power_products','Power Products (ANZ)','—','Awareness','Reach / engagement',NULL,'ANZ','Power_Products|Power Products'),
  STRUCT('digital_bldg','Digital Buildings','—','Awareness','Engagement',NULL,'ANZ','Digital Building|Digital Buildings'),
  STRUCT('digital_power','Digital Power Basket','—','Awareness','Traffic / engagement',NULL,'ANZ','Digital_Power_Basket|Power_Basket'),
  STRUCT('ecocare','EcoCare','—','Awareness','Traffic',NULL,'ANZ','EcoCare|Ecocare'),
  STRUCT('modernisation','Modernisation / SPaaS','—','LeadGen','Leads / conversions',NULL,'ANZ','Modernisation|Spaas|SPaaS'),
  STRUCT('active_kpx','Active KPX','—','Awareness','Awareness',NULL,'ANZ','Active KPX|Active_KPX| KPX_'),
  STRUCT('pac_hybrid_it','Pacific Hybrid IT','—','ABM','TAL website traffic','Hybrid IT','Pacific','Pacific Hybrid IT|Hybrid IT'),
  -- plan-only rows (referenced by the budget / flighting / targets seeds; no warehouse delivery
  -- matched yet — match_pattern is a best-guess, confirm against the plan / when they launch):
  STRUCT('heavy','Heavy Industries','—','Awareness','Reach / engagement',NULL,'ANZ','Heavy Indust|Heavy_Indust'),
  STRUCT('ecoconsult','EcoConsult','—','LeadGen','Traffic / SQLs / consults',NULL,'ANZ','EcoConsult|Eco Consult')
]);
