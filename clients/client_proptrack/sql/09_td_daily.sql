-- PropTrack (Transmission) — The Trade Desk daily delivery (the ~3-week burst, 2026-05-20 → 06-09).
-- Impressions (bars) + spend (line) per day on the Programmatic tab.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.td_daily` AS
SELECT
  metric_date,
  SUM(imps)        AS imps,
  SUM(clicks)      AS clicks,
  SUM(spend_aud)   AS spend_aud,
  SUM(conversions) AS conv
FROM `bidbrain-analytics.client_proptrack.stg_tradedesk`
GROUP BY metric_date
ORDER BY metric_date;
