-- Schneider Electric — GOOGLE SEARCH scope audit (added 2026-09-02). One row per Search campaign on
-- the account, with how it resolved and whether that is expected. The export job prints it every run
-- and WARNs; nothing renders from it.
--
-- WHY THIS EXISTS. Search is the first platform on this dashboard whose ad account is NOT
-- Pacific-only: 'AAG region Account' carries the brief-2306 campaigns running in Brazil, Chile,
-- Saudi Arabia and the UAE. Everything that keeps them off a Pacific dashboard is silent by nature:
--   * an unmatched campaign is DROPPED by the JOIN in 20_pm_delivery / 23_search_campaigns, and
--   * 20_pm_delivery's market normalisation is an `ELSE 'Australia'`, so a foreign row that DID get
--     in would be reported as Australian rather than rejected.
-- Under-inclusion is silent; over-inclusion is silent here too. This view makes both loud.
--
-- The repo rule it enforces (md/AGENTS.md, "A SCOPE FIX MEANT TO ADMIT ROWS MUST BE VERIFIED BY WHAT
-- IT ADMITS"): naming the campaigns a scope is supposed to let in, and asserting they are present,
-- is the only test that catches a fix that is a no-op for the wrong reason.
--
-- WHAT `expected` MEANS, campaign by campaign, as at 2026-09-02:
--   2061_AET - *            -> global_rebrand  IN SCOPE   AU + NZ, brand + 4 category lines, from 07-06.
--                                                         The lines the client asked for.
--   2389_SE_MCSeT EvoPacT * -> mcset           IN SCOPE   ANZ brand + non-brand, from 08-10.
--   2306_SE_AI&LiquidCooling_* -> ai_lc        OUT, BY DESIGN. Brief 2306 has its OWN dashboard
--                                                         (client_schneiderlqai, reported in EUR) and
--                                                         runs AU/BR/CL/SA/UAE. Excluded by PROGRAM,
--                                                         never by region.
--   2353_MEA_Healthcare.    -> mea_seg         OUT, BY DESIGN. One YouTube row, 2026-04-25, MEA.
--                                                         Noise; not a Pacific program.
--
-- HOW TO READ A FLAG:
--   status='UNMAPPED'          a campaign matched NO seed_campaign_map token. It is invisible on every
--                              surface. Either add a token to the owning program (and simulate first),
--                              or add one to the program that should own it out of scope, so the
--                              exclusion is recorded rather than accidental.
--   status='IN_SCOPE_NON_ANZ'  an in-scope program is delivering Search outside Australia/NZ. Its
--                              spend is currently being reported AS AUSTRALIA by 20_pm_delivery's
--                              fold. Add the multi-region arm described in that view BEFORE trusting
--                              any market number for it.
--   status='OUT_OF_SCOPE'      resolved to a program the dashboard does not show. Expected for 2306
--                              and 2353. A NEW program appearing here is a scope question for the
--                              client (the intake-sheet rule), not a bug to fix in SQL.
--   status='IN_SCOPE'          normal.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.search_scope_audit` AS
WITH camp AS (
  SELECT
    campaign_name,
    ANY_VALUE(campaign_id)  AS campaign_id,
    ANY_VALUE(brief)        AS brief,
    MIN(metric_date)        AS first_day,
    MAX(metric_date)        AS last_day,
    SUM(imps)               AS imps,
    SUM(clicks)             AS clicks,
    SUM(spend_aud)          AS spend_aud,
    SUM(cost_usd)           AS cost_usd,
    STRING_AGG(DISTINCT market, ' / ' ORDER BY market) AS markets,
    STRING_AGG(DISTINCT IFNULL(network, '(none)'), ' / ' ORDER BY IFNULL(network, '(none)')) AS networks
  FROM `bidbrain-analytics.client_schneider.stg_google_search`
  GROUP BY campaign_name
)
SELECT
  c.campaign_name,
  c.campaign_id,
  c.brief,
  cp.program,
  c.markets,
  c.networks,
  c.first_day,
  c.last_day,
  c.imps,
  c.clicks,
  c.spend_aud,
  c.cost_usd,
  -- Must stay identical to the IN-list in 20_pm_delivery / 23_search_campaigns.
  cp.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult',
                 'mcset') AS in_scope,
  CASE
    WHEN cp.program IS NULL THEN 'UNMAPPED'
    WHEN cp.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid',
                        'ecoconsult','mcset')
         AND NOT REGEXP_CONTAINS(c.markets, r'^(Australia|New Zealand|ANZ)( / (Australia|New Zealand|ANZ))*$')
      THEN 'IN_SCOPE_NON_ANZ'
    WHEN cp.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid',
                        'ecoconsult','mcset') THEN 'IN_SCOPE'
    ELSE 'OUT_OF_SCOPE'
  END AS status
FROM camp c
LEFT JOIN `bidbrain-analytics.client_schneider.campaign_program` cp
  ON cp.campaign = c.campaign_name
ORDER BY status, c.campaign_name;
