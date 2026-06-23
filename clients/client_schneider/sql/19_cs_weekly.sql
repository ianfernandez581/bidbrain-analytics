-- Schneider Electric — CS leads per campaign × programme × market × ISO week. Powers the Content
-- Syndication "Weekly pacing — target vs actual" chart and the CS Comparison weekly panels. Unlike
-- client_mongodb (whose leads aren't date-stamped, so it RAMPS the actuals), Schneider's SF leads
-- carry a real DAY, so this is true weekly actuals. Reads stg_salesforce (view 17).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.cs_weekly` AS
SELECT
  campaign,
  programme,
  market,
  DATE_TRUNC(metric_date, WEEK(MONDAY)) AS week_start,
  SUM(leads)                            AS leads
FROM `bidbrain-analytics.client_schneider.stg_salesforce`
GROUP BY campaign, programme, market, week_start
ORDER BY week_start, campaign;
