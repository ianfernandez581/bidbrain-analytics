-- ResetData — Trade Desk delivery by campaign (whole flight). Spend AUD (USD→AUD @1.50 in
-- stg_ttd). No conversions column — TTD reports none upstream. Per-campaign table on Paid Media.
-- Delivering rows only via an outer WHERE (see 13 for the aggregation-of-aggregation note).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ttd_campaigns` AS
WITH agg AS (
  SELECT
    campaign,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_ttd`
  GROUP BY campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
