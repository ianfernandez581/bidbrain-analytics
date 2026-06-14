-- TLM — Trade Desk delivery by campaign (whole flight). Spend AUD (Windsor already AUD;
-- FX case at 1.50 in stg_ttd is present but passes through unchanged). No conversions
-- column — TTD pixel fires are anonymous with no revenue attribution. Per-campaign table
-- on the Trade Desk tab. Delivering rows only via outer WHERE.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.ttd_campaigns` AS
WITH agg AS (
  SELECT
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_tlm.stg_ttd`
  GROUP BY campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;