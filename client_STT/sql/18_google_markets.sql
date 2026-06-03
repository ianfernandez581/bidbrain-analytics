-- STT GDC — Google Ads paid-search delivery by market (whole flight). Spend is SGD (USD rows converted).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.google_markets` AS
SELECT
  market,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_sgd)   AS spend_sgd,
  SUM(conversions) AS conversions
FROM `bidbrain-analytics.client_stt.stg_google`
GROUP BY market
ORDER BY imps DESC;
