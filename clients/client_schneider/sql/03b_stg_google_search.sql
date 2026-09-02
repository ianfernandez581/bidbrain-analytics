-- Schneider Electric (APAC, via Transmission) — staged GOOGLE ADS (Search / SEM), added 2026-09-02.
--
-- The FOURTH ad platform on this dashboard, after DV360 / The Trade Desk / LinkedIn. Data has been
-- in the warehouse since 2026-07-06 but reached no surface until now; the client asked for it.
--
-- SOURCE: the shared raw_snowflake.google_ads_apac mirror (Snowflake
-- `APAC_ALL_PLATFORM.PUBLIC."Google Ads - APAC"`). CAMPAIGN-level grain, one row per campaign per
-- day, no network split on this account (verified 2026-09-02: NETWORK is single-valued per campaign).
--
-- THE SCHNEIDER FILTER LIVES HERE ONCE: ACCOUNT_NAME = 'AAG region Account' (ACCOUNT_ID 2494240566).
-- **The account name gives no hint that it is Schneider's** — do NOT try to filter this platform on
-- anything containing "schneider"; there is no such string on any row. The three sibling accounts in
-- the same mirror are STT's and Cloudflare's, so the equality test is the whole scope.
--
-- ACCOUNT-LEVEL IS THE RIGHT FILTER *HERE* AND THE WRONG ONE DOWNSTREAM. This is a STAGING view and
-- mirrors what stg_dv360 / stg_tradedesk / stg_linkedin do — stage the whole advertiser, then let
-- 20_pm_delivery scope to the dashboard's programs via seed_campaign_map. That matters more on this
-- platform than on any other, because **this account is NOT ANZ-only**: the five
-- `2306_SE_AI&LiquidCooling_*` campaigns run in Brazil, Chile, Saudi Arabia and the UAE. They are
-- NOT in this dashboard's scope (brief 2306 is `ai_lc`, which has its own dashboard,
-- client_schneiderlqai, whose sql/05_stg_google_search already reports them in EUR), and they are
-- excluded by PROGRAM in 20_pm_delivery — never by region here.
--   >> Any Pacific-scoped consumer must filter at CAMPAIGN/PROGRAM level, never account level. <<
-- 20_pm_delivery's AU/NZ market fold is a silent `ELSE`, so a 2306 row that ever reached it would be
-- reported AS AUSTRALIA. Two things stop that, and both are deliberate: (1) `2306_` was added to
-- ai_lc's match_pattern so those campaigns map to an out-of-scope program BY DESIGN rather than
-- falling through unmatched by luck, and (2) 23_search_scope_audit re-checks it every run and the
-- export job WARNs. Read that view before loosening anything here.
--
-- CURRENCY: this account bills in USD (verified on every row) while the dashboard reports AUD.
-- Converted at the SHARED Schneider constant FX_USD_AUD = 1.50 (see the stg_dv360 header — the same
-- number stg_linkedin and stg_tradedesk use), so Search spend is on exactly the same basis as the
-- other three platforms and may be summed with them. `cost_usd` is carried ALONGSIDE `spend_aud` so
-- the source figure stays recoverable and the dashboard can footnote the conversion explicitly —
-- required, because Search is the only platform here whose native currency is never AUD.
-- CURRENCY sits in the GROUP BY rather than in a WHERE: the split-loudly pattern (a source-side
-- currency change splits into a second, visible row instead of silently mislabelling cost).
--
-- CONVERSIONS ARE DELIBERATELY ABSENT — DO NOT ADD THEM. The mirror carries CONVERSIONS,
-- CONVERSION_RATE, COST_PER_CONVERSION and CONVERSION_VALUE_TOTAL for this account and they are
-- UNRESOLVED: the figure is either correct or inflated ~100x and the warehouse cannot settle which.
-- The obvious sanity check does not help — the account's conversion actions are dominated by
-- page-view tags, so >1 conversion per click is genuinely plausible (2061_AET Branded reports 12,616
-- conversions on 1,630 clicks). The cross-check table "Google Ads - APAC ALL - Conversion" disagrees
-- with this campaign table for the same account and day, so it settles nothing either. Nothing may
-- be displayed, computed or DERIVED from those four columns until a manual reconciliation against
-- the Google Ads UI lands — that includes CPA and ROAS. Not selecting them at all is the
-- enforcement: a column that is not in the view cannot be summed by accident three layers
-- downstream. The dashboard carries a labelled placeholder where the panel will go.
--
-- MATCH_TYPE (Brand vs Non-brand) is the dimension that actually matters on Search, and it is why
-- this view keeps campaign grain. Brand and non-brand Search are not comparable — 2061_AET's branded
-- lines run ~28% CTR at ~A$0.26 a click while its category lines run ~5% CTR at ~A$4 — so a single
-- blended Search CTR describes neither. The ladder is MOST-SPECIFIC-FIRST because **'NonBrand'
-- CONTAINS 'Brand'** (the same trap as 'CONVERSION' containing 'CON' in client_schneidersecpwr's
-- tactic ladder): test non-brand BEFORE brand, or every non-brand campaign reads as brand. A
-- campaign that says neither is 'Non-brand' — the honest default, since brand terms are always
-- labelled while generic terms often are not; it is never silently folded into Brand.
--
-- MARKET is parsed with the SAME boundary-anchored regex family as stg_linkedin / stg_tradedesk
-- (`(^|[ _-])AU([ _-]|$)`), NOT `LIKE '%_au_%'` — `_` is a wildcard in LIKE and a loose 'AU' also
-- matches inside "AUTOMATION", which `2061_AET - Electrification & Automation - AU` literally
-- contains. Trailing ' - AU' / ' - NZ' on the 2061 lines and '_ANZ_' on the 2389 lines both resolve;
-- anything else falls to 'Unmapped' rather than to a country, so an unparsed market stays visible
-- instead of being invented. BRIEF is the leading job-number token, carried for the scope audit.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.stg_google_search` AS
SELECT
  DATE(DAY)                                AS metric_date,
  CAMPAIGN_NAME                            AS campaign_name,
  CAMPAIGN_ID                              AS campaign_id,
  -- brief / job number: the leading digits before the first '_' ('2061', '2306', '2389', '2353').
  REGEXP_EXTRACT(CAMPAIGN_NAME, r'^([0-9]+)_')  AS brief,
  NULLIF(TRIM(IFNULL(NETWORK, '')), '')    AS network,
  CURRENCY                                 AS currency,
  -- Brand vs Non-brand. MOST-SPECIFIC-FIRST: 'NonBrand' contains 'Brand'.
  CASE
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)non.?brand') THEN 'Non-brand'
    WHEN REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)brand')      THEN 'Brand'
    ELSE 'Non-brand'
  END                                      AS match_type,
  -- market — identical parser family to stg_linkedin / stg_tradedesk. Country tokens win over the
  -- coarse region tokens; ANZ wins over Pacific. First match wins. Else -> 'Unmapped'.
  CASE
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])AU([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Australia') THEN 'Australia'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])NZ([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)New ?Zealand') THEN 'New Zealand'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])ANZ([ _-]|$)') THEN 'ANZ'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'INDIA') THEN 'India'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(JP|JAPAN)([ _-]|$)') OR CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Japan') THEN 'Japan'
    -- NB: on THIS account 'SA' is Saudi Arabia, not South America (2306_SE_AI&LiquidCooling_SA_SEM_AWR).
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'MEA') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(UAE|KSA|SA)([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Saudi|Qatar|Egypt|Emirates)') THEN 'MEA'
    WHEN REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])(BR|CL|AR|MX|CO)([ _-]|$)') OR REGEXP_CONTAINS(CAMPAIGN_NAME, r'(?i)(Brazil|Chile|Argentina|Mexico|Colombia|South America|LATAM)') THEN 'South America'
    WHEN CONTAINS_SUBSTR(UPPER(CAMPAIGN_NAME), 'SEA') THEN 'SEA'
    WHEN CONTAINS_SUBSTR(CAMPAIGN_NAME, 'Pacific') OR REGEXP_CONTAINS(UPPER(CAMPAIGN_NAME), r'(^|[ _-])PAC([ _-]|$)') THEN 'Pacific'
    ELSE 'Unmapped'
  END                                      AS market,
  SUM(IMPRESSIONS)                         AS imps,
  SUM(CLICKS)                              AS clicks,
  SUM(COSTS)                               AS cost_usd,
  -- FX_USD_AUD = 1.50 (shared Schneider constant, see stg_dv360). Every row on this account is USD;
  -- the CASE keeps it honest if that ever stops being true rather than silently mis-converting.
  SUM(CASE WHEN CURRENCY = 'USD' THEN COSTS * 1.50 ELSE COSTS END) AS spend_aud
FROM `bidbrain-analytics.raw_snowflake.google_ads_apac`
WHERE ACCOUNT_NAME = 'AAG region Account'
GROUP BY metric_date, campaign_name, campaign_id, brief, network, currency, match_type, market;
