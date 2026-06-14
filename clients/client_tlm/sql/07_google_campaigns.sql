-- TLM — Google Ads delivery by campaign (whole flight) + platform-reported conversions/revenue.
-- Per-campaign table on the Google Ads tab. ROAS / AOV / CPA are derived client-side.
-- Delivering rows only via an outer WHERE (not HAVING SUM(alias), which BigQuery would read as
-- an aggregation-of-aggregation against the SELECT alias).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.google_campaigns` AS
WITH agg AS (
  SELECT
    campaign,
    campaign_type,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,
    SUM(revenue)     AS revenue,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_tlm.stg_google`
  GROUP BY campaign, campaign_type
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;