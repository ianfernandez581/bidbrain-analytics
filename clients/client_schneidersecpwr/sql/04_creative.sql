-- Secure Power creative performance — one row per campaign × platform × market × concept × format ×
-- creative, WHOLE FLIGHT (no date column). Backs the Creative tab.
--
-- Because these rows carry no date, the dashboard filters them by the campaign / market / platform
-- chips ONLY - the date-range picker does not narrow them, and the UI says so on the tab. (Same
-- deliberate limitation as client_schneiderlqai and client_cloudflare; adding a date column here
-- would multiply the row count for a table that is read as a whole-flight ranking.)
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.creative` AS
WITH u AS (
  SELECT campaign, platform, market, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_linkedin`
  UNION ALL
  SELECT campaign, platform, market, concept, creative_format, creative_name, imps, clicks, spend_aud
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_tradedesk`
)
SELECT
  campaign,
  platform,
  market,
  concept,
  creative_format,
  creative_name,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_aud)                           AS spend_aud
FROM u
GROUP BY campaign, platform, market, concept, creative_format, creative_name;
