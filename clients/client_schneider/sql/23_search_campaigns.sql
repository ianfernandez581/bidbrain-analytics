-- Schneider Electric — GOOGLE SEARCH detail at CAMPAIGN grain, scoped to the dashboard's programs
-- (added 2026-09-02, alongside 03b_stg_google_search).
--
-- WHY A SEPARATE VIEW instead of un-grouping 20_pm_delivery: that view is deliberately aggregated to
-- program x platform x day x market and carries NO campaign column — un-grouping it once pushed
-- schneider.json to 13.6 MB (see its GROUP BY note, which says to add a separate view if campaign
-- grain is ever needed). This is that view, and it is Search-only, so the cost is bounded: ~11
-- in-scope campaigns x ~60 days, a few hundred rows, not the ~73k the ungrouped version emitted.
--
-- WHY CAMPAIGN GRAIN AT ALL: the split that matters on Search is BRAND vs NON-BRAND, and it lives in
-- the campaign name. Blending them gives a Search CTR that describes neither lane (2061_AET brand
-- runs ~28% CTR at ~A$0.26/click; its category line runs ~5% at ~A$4). MARKET x MATCH_TYPE is the
-- grid the dashboard's Search section is built on.
--
-- SCOPE + MARKET are resolved EXACTLY as 20_pm_delivery does, from the same campaign_program view
-- and the same program IN-list, so the Search section can never disagree with the Google Search row
-- of the platform table above it. The two lists MUST stay in sync (and in sync with CS_PROGRAMS in
-- job/main.py) — that is the dashboard's one scope rule. `market` keeps the raw parsed value AND a
-- folded `market_anz` that matches pm_delivery's AU/NZ normalisation, so the Search tables answer to
-- the same Region chips as every other number on the tab while the true parse stays inspectable.
--
-- NO CONVERSION COLUMNS. See 03b_stg_google_search — the account's CONVERSIONS family is unresolved
-- (possibly inflated ~100x) and nothing may be displayed or derived from it, CPA and ROAS included,
-- until a manual reconciliation against the Google Ads UI lands. cost_usd rides along so the AUD
-- figure can be footnoted with the source amount and the rate it was converted at.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.search_campaigns` AS
SELECT
  cp.program,
  s.metric_date,
  s.campaign_name,
  s.campaign_id,
  s.brief,
  s.match_type,
  s.network,
  s.currency,
  s.market                              AS market_parsed,
  -- IDENTICAL fold to 20_pm_delivery, so this view answers to the same Region chips.
  CASE WHEN s.market = 'New Zealand' THEN 'New Zealand' ELSE 'Australia' END AS market,
  SUM(s.imps)      AS imps,
  SUM(s.clicks)    AS clicks,
  SUM(s.spend_aud) AS spend_aud,
  SUM(s.cost_usd)  AS cost_usd
FROM `bidbrain-analytics.client_schneider.stg_google_search` s
JOIN `bidbrain-analytics.client_schneider.campaign_program` cp
  ON cp.campaign = s.campaign_name
-- Same scope list as 20_pm_delivery. Keep them identical.
WHERE cp.program IN ('water_env','eba','heavy','global_rebrand','airset','nel','microgrid','ecoconsult','mcset')
GROUP BY 1,2,3,4,5,6,7,8,9,10;
