-- Content engagement: delivery mix (impressions / spend / clicks) across the
-- dimensions the raw_snowflake mirror drops — device, ad environment, creative
-- size. Long form (DIM, LABEL, ...) so the export job and dashboard pivot it
-- without one view per cut. ORDER BY at the end is per-DIM via the IMPS sort.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.pixel_dims` AS
SELECT 'device' AS DIM, DEVICE_TYPE AS LABEL,
       SUM(IMPRESSIONS) AS IMPS, SUM(COST_USD) AS COST_USD, SUM(CLICKS) AS CLICKS
FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel`
WHERE COALESCE(DEVICE_TYPE, '') != ''
GROUP BY DEVICE_TYPE
UNION ALL
SELECT 'environment', AD_ENVIRONMENT,
       SUM(IMPRESSIONS), SUM(COST_USD), SUM(CLICKS)
FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel`
WHERE COALESCE(AD_ENVIRONMENT, '') != ''
GROUP BY AD_ENVIRONMENT
UNION ALL
SELECT 'format', AD_FORMAT,
       SUM(IMPRESSIONS), SUM(COST_USD), SUM(CLICKS)
FROM `bidbrain-analytics.client_mongodb.seed_tradedesk_pixel`
WHERE COALESCE(AD_FORMAT, '') != ''
GROUP BY AD_FORMAT
ORDER BY DIM, IMPS DESC
