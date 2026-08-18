-- Secure Power creative performance — one row per campaign × platform × tactic × market × concept ×
-- format × creative, WHOLE FLIGHT (no date column). Backs the Creative tab.
--
-- `tactic` (the media-plan line item) is carried here as well as in `delivery` so the Creative tab
-- honours the same line-item filter as the rest of the dashboard, and so "which creative ran in which
-- funnel stage" is answerable - the same creative is frequently reused across stages, and rolling
-- those up would have hidden that. Added 2026-08-18 with the rest of the line-item work.
--
-- Because these rows carry no date, the dashboard filters them by the campaign / line item / market /
-- channel chips ONLY - the date-range picker does not narrow them, and the UI says so on the tab.
-- (Same deliberate limitation as client_schneiderlqai and client_cloudflare; adding a date column
-- here would multiply the row count for a table that is read as a whole-flight ranking.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.creative` AS
WITH u AS (
  SELECT campaign, platform, market, tactic, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_linkedin`
  UNION ALL
  SELECT campaign, platform, market, tactic, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_tradedesk`
)
SELECT
  campaign,
  platform,
  market,
  tactic,
  concept,
  creative_format,
  creative_name,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_aud)                           AS spend_aud
FROM u
GROUP BY campaign, platform, market, tactic, concept, creative_format, creative_name;
