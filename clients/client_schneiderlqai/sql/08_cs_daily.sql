-- LQAIDC content syndication — DAILY lead delivery (day x vendor x region x country x status).
--
-- DAY grain on purpose: the dashboard's date picker must be able to honour a range that cuts
-- mid-week, which week buckets cannot do (the cloudflare 18_cs_compare_v2 rule). The dashboard
-- aggregates up to whatever grain it is drawing.
--
-- Keyed on DAY (the lead's Salesforce date), NEVER on DT_CREATED: the mirror loads in bulk, so
-- DT_CREATED is a single identical instant across thousands of rows and would draw the entire
-- flight as one spike on one day (the client_cloudflare 14_cf1_cs trap).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneiderlqai.cs_daily` AS
SELECT
  metric_date,
  vendor,
  region,
  country,
  status_bucket,
  SUM(leads)                                   AS leads
FROM `bidbrain-analytics.client_schneiderlqai.stg_salesforce`
GROUP BY metric_date, vendor, region, country, status_bucket;
