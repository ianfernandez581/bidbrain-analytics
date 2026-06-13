-- STT GDC — DV360 programmatic delivery by market (whole flight). Spend is SGD.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.dv_markets` AS
SELECT
  market,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_sgd)   AS spend_sgd,
  SUM(conversions) AS conversions
FROM `bidbrain-analytics.client_stt.stg_dv360`
GROUP BY market
ORDER BY imps DESC;
