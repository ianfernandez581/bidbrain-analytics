-- ResetData — Meta delivery by campaign (whole flight) + platform-reported leads.
-- Per-campaign table on the Paid Media tab. Leads are sparse (B2B) — shown as-is.
-- Delivering rows only via an outer WHERE (see 13 for the aggregation-of-aggregation note).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.meta_campaigns` AS
WITH agg AS (
  SELECT
    campaign,
    SUM(imps)               AS imps,
    SUM(clicks)             AS clicks,
    SUM(link_clicks)        AS link_clicks,
    SUM(landing_page_views) AS landing_page_views,
    SUM(spend_aud)          AS spend_aud,
    SUM(conversions)        AS conversions,
    MIN(metric_date)        AS start_date,
    MAX(metric_date)        AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_meta`
  GROUP BY campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
