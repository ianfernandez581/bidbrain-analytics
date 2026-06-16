-- Schneider Electric — SEED: campaign map (the human bridge between the media-plan campaigns
-- and the raw platform campaign names). One row per internal campaign. Editable in-repo as a
-- STRUCT array. The dashboard joins each delivering platform campaign to a row by testing
-- whether the platform CAMPAIGN_NAME CONTAINS any of the '|'-separated match_pattern tokens
-- (case-insensitive, FIRST ROW IN THIS ARRAY ORDER WINS); unmatched delivery falls back to
-- display '(unmapped)' so nothing breaks.
--
-- PORTFOLIO (2026-06-16, Transmission/Gabby O'Driscoll direction): 'portfolio' splits the book of
-- work so the **Pacific** programs are COMPLETELY SEPARATE from the rest. The dashboard DEFAULTS to
-- portfolio='Pacific' (with a Pacific / APAC-other / All toggle). NB: this is the ORGANISATIONAL
-- Pacific (a named set of SE programs owned by the Pacific team) — NOT the geographic 'Pacific'
-- region chip on the Geography tab (Fiji/PNG/… parsed from campaign names), which is left untouched.
--   * portfolio='Pacific' == EXACTLY the client's named Pacific program list (Heavy, AirSeT, EBA,
--     Water & Environment, Global Rebrand, MCSeT & EvoPacT, EcoConsult, Healthcare, Microgrid,
--     EcoCare BMS, Enterprise Software). Everything else (incl. the explicit excludes AI & Liquid
--     Cooling / Enterprise IT Expansion / C&SP) is 'APAC-other'.
--   * JUDGMENT CALLS to confirm with the client (flip the one tag if wrong):
--       - ind_edge ('Industrial Edge') + pac_hybrid_it ('Pacific Hybrid IT') are NAMED "Pacific" in
--         the platform but are NOT on the client's Pacific PROGRAM list → tagged 'APAC-other' (the
--         org-vs-geo trap). Flip to 'Pacific' if the client says these belong to the Pacific book.
--       - ecocare is tagged 'Pacific' as the client's "EcoCare BMS" (delivery is literally
--         '..._Ecocare_BMS_...'); NEEDS-CONFIRMATION that EcoCare BMS ≡ this existing id.
--       - enterprise_software is a NEW placeholder, NEEDS-CONFIRMATION it is NOT the excluded
--         ent_it ('Enterprise IT Expansion').
--
-- brief_job_no = the BRIEF's job number (canonical, from the client Drive); '—' where none known.
-- It is NOT the platform PO code (those differ — e.g. csp brief 1957 ↔ platform PO 1608 — and are
-- intentionally NOT reconciled here). The match_pattern is the only delivery bridge, never the job no.
--   Canonical job numbers corrected 2026-06-16 from the client Drive (the old values were stale):
--     water_env 1130→2026 · mcset 1130→2389 · ind_edge 1839→2463 · eae —→1974 · ia_services —→2280
--     heavy 2281 · ecoconsult 2279 · airset 2223 (NEW) · eba 2079 (NEW, split from eae — see below).
--
-- objective_type ∈ {Awareness, LeadGen, ABM, Event, Awareness→RT}. primary_kpi is free text.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.seed_campaign_map` AS
SELECT * FROM UNNEST([
  STRUCT(
    'eae' AS internal_campaign_id, 'EcoStruxure Automation Expert' AS display_name,
    '1974' AS brief_job_no, 'LeadGen' AS objective_type, 'Opt-in MQLs' AS primary_kpi,
    CAST(NULL AS STRING) AS pillar, 'ANZ' AS primary_region,
    'Ecostructure_Automation_Expert|Automation_Expert|Automation Expert' AS match_pattern,
    'APAC-other' AS portfolio),
  -- EBA — EcoStruxure Building Activate. SPLIT into its own row (was tangled into eae: the 300
  -- opt-in MQL target on eae was sourced from the EBA brief, not EAE — target moved to eba in
  -- seed_targets). Delivery 'SE_EBA_Activate_AWR_June4' (TradeDesk) previously fell to (unmapped).
  STRUCT('eba','EcoStruxure Building Activate','2079','LeadGen','Opt-in MQLs',NULL,'ANZ',
         'EBA_Activate|Building Activate|EBA_','Pacific'),
  STRUCT('aveva','AVEVA','—','LeadGen','Opt-in MQLs',NULL,'ANZ','AVEVA','APAC-other'),
  STRUCT('ai_lc','AI & Liquid Cooling','2306','Awareness','Top-funnel engagement',NULL,'multi','AI in DC|LQAIDC|AI in DC ','APAC-other'),
  STRUCT('csp','C&SP Relationship Marketing','1957','ABM','Brand preference & opps',NULL,'multi','C&SP','APAC-other'),
  STRUCT('ent_it','Enterprise IT Expansion','1958','ABM','Hand-raisers + MQLs',NULL,'multi','EntIT','APAC-other'),
  STRUCT('water_env','Water & Environment','2026','Awareness','Reach / Clicks / LP lands','3 pillars','ANZ','WaterEnv','Pacific'),
  STRUCT('ind_edge','Industrial Edge / Prefab','2463','LeadGen','Qualified leads / CPL / CVR',NULL,'Pacific','Industrial Edge','APAC-other'),
  STRUCT('mcset','MCSeT + EvoPacT','2389','Event','Roadshow registrations',NULL,'ANZ','Cooling Solutions','Pacific'),
  STRUCT('ia_services','IA Services','2280','Awareness→RT','Reach / freq, VCR',NULL,'ANZ','AI Services','APAC-other'),
  STRUCT('impact_maker','Impact Maker','1914','Awareness','Reach / engagement',NULL,'ANZ','Impact_Maker|Imapct_Maker','APAC-other'),
  STRUCT('iof','Industries of the Future','1899','Awareness','Engagement',NULL,'multi','IOF|Industries of the Future','APAC-other'),
  STRUCT('mea_seg','MEA Segment Program','2353','ABM','TAL engagement','MEA','MEA','2353|MEA Segment','APAC-other'),
  -- [delivery] inferred from observed platform campaigns — confirm against the plan:
  STRUCT('power_products','Power Products (ANZ)','—','Awareness','Reach / engagement',NULL,'ANZ','Power_Products|Power Products','APAC-other'),
  STRUCT('digital_bldg','Digital Buildings','—','Awareness','Engagement',NULL,'ANZ','Digital Building|Digital Buildings','APAC-other'),
  STRUCT('digital_power','Digital Power Basket','—','Awareness','Traffic / engagement',NULL,'ANZ','Digital_Power_Basket|Power_Basket','APAC-other'),
  -- ecocare == the client's "EcoCare BMS" Pacific program (delivery is literally '..._Ecocare_BMS_...').
  -- NEEDS-CONFIRMATION that EcoCare BMS ≡ this id before fully trusting the Pacific tag.
  STRUCT('ecocare','EcoCare BMS','—','Awareness','Traffic',NULL,'ANZ','EcoCare|Ecocare','Pacific'),
  STRUCT('modernisation','Modernisation / SPaaS','—','LeadGen','Leads / conversions',NULL,'ANZ','Modernisation|Spaas|SPaaS','APAC-other'),
  STRUCT('active_kpx','Active KPX','—','Awareness','Awareness',NULL,'ANZ','Active KPX|Active_KPX| KPX_','APAC-other'),
  -- pac_hybrid_it: NAMED "Pacific Hybrid IT" but NOT on the client's Pacific program list → APAC-other
  -- (org-vs-geo). Flip to 'Pacific' if the client says it belongs to the Pacific book.
  STRUCT('pac_hybrid_it','Pacific Hybrid IT','—','ABM','TAL website traffic','Hybrid IT','Pacific','Pacific Hybrid IT|Hybrid IT','APAC-other'),
  -- ============ PACIFIC plan-only / newly-mapped rows ============
  -- AirSeT — NEW. 5 LinkedIn campaigns ('RM/SM AirSeT – Awareness/Retargeting – ANZ/AU/NZ', en-dash
  -- separators) previously fell to (unmapped); 'AirSeT' token catches them (validated against the
  -- Phase-1 unmapped list — matches exactly those 5, nothing else).
  STRUCT('airset','AirSeT','2223','Awareness→RT','Reach / engagement',NULL,'ANZ','AirSeT|AirSet','Pacific'),
  STRUCT('heavy','Heavy Industries','2281','Awareness','Reach / engagement',NULL,'ANZ','Heavy Indust|Heavy_Indust','Pacific'),
  STRUCT('ecoconsult','EcoConsult','2279','LeadGen','Traffic / SQLs / consults',NULL,'ANZ','EcoConsult|Eco Consult','Pacific'),
  -- Placeholders for Pacific programs not yet delivering (live Jul/Aug/TBC). match_pattern is a
  -- NON-MATCHING sentinel today (esp. 'healthcare' which must NOT steal the *_Healthcare_AdGroup
  -- audience segments of ent_it/ecocare) — set the real pattern when each launches.
  STRUCT('global_rebrand','Global Rebrand Activation','—','Awareness','Reach / engagement',NULL,'ANZ','Global Rebrand|Global_Rebrand|Rebrand Activation','Pacific'),
  STRUCT('healthcare','Healthcare','—','Awareness','Reach / engagement',NULL,'ANZ','Healthcare_Vertical_TBC','Pacific'),
  STRUCT('microgrid','Microgrid','—','Awareness','Reach / engagement',NULL,'ANZ','Microgrid|Micro Grid|Micro_Grid','Pacific'),
  -- enterprise_software — NEEDS-CONFIRMATION identity. Distinct from ent_it (Enterprise IT, excluded).
  STRUCT('enterprise_software','Enterprise Software','—','LeadGen','Leads / conversions',NULL,'ANZ','Enterprise_Software_TBC|EntSoftware','Pacific')
]);
