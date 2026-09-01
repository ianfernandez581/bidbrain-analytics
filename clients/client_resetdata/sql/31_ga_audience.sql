-- ResetData — Google Ads AD-AUDIENCE demographics (age / gender / device) for the Overview.
--
-- "Who the ADS reached" — Google's inferred demographics of the people the Google Ads campaigns
-- served to. NOT website-visitor demographics: GA4's DemographicDetails export for this property is
-- EMPTY (Google thresholds demographics on low-traffic sites), so Google Ads is the only source of
-- audience insight here. Frame it in-app as "ad audience reached (Google Ads)".
--
-- Source = the native BigQuery DTS tables in raw_google_ads (the same daily transfer the
-- perf_google_ads bridge reads), scoped to ResetData's customer_id 1054407474 (manager/login-customer
-- 1054407474). **TWO table sets, split on one cutover date (2026-08-31):** the MCC-wide set
-- `*_3451896252` holds every day up to 2026-08-24 and can never gain another - Google stopped
-- serving metrics at manager level on 08-18 - and Reset Data's OWN per-account set takes over
-- from 08-25. Reading only the new set would have silently dropped 7 months of history here
-- (28,143 rows -> 116); reading both unbounded would double-count the overlap a DTS refresh
-- window creates. Same cutover as `raw_google_ads.perf_google_ads`; see md/AGENTS.md.
-- Age/gender labels come from Google Ads' fixed global criterion
-- IDs; device from segments_device (summed over the age table's age×device grain = device totals).
-- cost_micros -> AUD via /1e6 (the RAW DTS metric is micros, unlike the perf_google_ads bridge).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga_audience` AS
WITH age_src AS (
  SELECT ad_group_criterion_criterion_id, segments_device, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_AgeRangeBasicStats_3451896252`
  WHERE customer_id = 1054407474 AND segments_date <= DATE '2026-08-24'
  UNION ALL
  SELECT ad_group_criterion_criterion_id, segments_device, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_AgeRangeBasicStats_1054407474`
  WHERE segments_date >= DATE '2026-08-25'
),
gender_src AS (
  SELECT ad_group_criterion_criterion_id, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_GenderBasicStats_3451896252`
  WHERE customer_id = 1054407474 AND segments_date <= DATE '2026-08-24'
  UNION ALL
  SELECT ad_group_criterion_criterion_id, metrics_impressions, metrics_clicks, metrics_cost_micros, metrics_conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_GenderBasicStats_1054407474`
  WHERE segments_date >= DATE '2026-08-25'
),
age AS (
  SELECT 'age' AS dim,
    CASE ad_group_criterion_criterion_id
      WHEN 503001 THEN '18-24' WHEN 503002 THEN '25-34' WHEN 503003 THEN '35-44'
      WHEN 503004 THEN '45-54' WHEN 503005 THEN '55-64' WHEN 503006 THEN '65+'
      ELSE 'Undetermined' END                       AS bucket,
    SUM(metrics_impressions)                        AS imps,
    SUM(metrics_clicks)                             AS clicks,
    ROUND(SUM(metrics_cost_micros) / 1e6, 2)        AS spend_aud,
    ROUND(SUM(metrics_conversions), 1)              AS conversions
  FROM age_src
  GROUP BY bucket
),
gender AS (
  SELECT 'gender' AS dim,
    CASE ad_group_criterion_criterion_id WHEN 10 THEN 'Male' WHEN 11 THEN 'Female' ELSE 'Undetermined' END AS bucket,
    SUM(metrics_impressions), SUM(metrics_clicks),
    ROUND(SUM(metrics_cost_micros) / 1e6, 2), ROUND(SUM(metrics_conversions), 1)
  FROM gender_src
  GROUP BY bucket
),
device AS (
  SELECT 'device' AS dim,
    INITCAP(REPLACE(segments_device, '_', ' '))     AS bucket,   -- MOBILE->Mobile, CONNECTED_TV->Connected Tv
    SUM(metrics_impressions), SUM(metrics_clicks),
    ROUND(SUM(metrics_cost_micros) / 1e6, 2), ROUND(SUM(metrics_conversions), 1)
  FROM age_src
  GROUP BY bucket
)
SELECT * FROM (
  SELECT * FROM age UNION ALL SELECT * FROM gender UNION ALL SELECT * FROM device
)
WHERE imps > 0
ORDER BY dim, imps DESC;
