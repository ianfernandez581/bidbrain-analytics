-- ResetData — Google Ads AD-AUDIENCE demographics (age / gender / device) for the Overview.
--
-- "Who the ADS reached" — Google's inferred demographics of the people the Google Ads campaigns
-- served to. NOT website-visitor demographics: GA4's DemographicDetails export for this property is
-- EMPTY (Google thresholds demographics on low-traffic sites), so Google Ads is the only source of
-- audience insight here. Frame it in-app as "ad audience reached (Google Ads)".
--
-- Source = the native BigQuery DTS tables in raw_google_ads (the same daily transfer the
-- perf_google_ads bridge reads), scoped to ResetData's customer_id 1054407474 (manager/login-customer
-- 3451896252 is the dataset suffix). Age/gender labels come from Google Ads' fixed global criterion
-- IDs; device from segments_device (summed over the age table's age×device grain = device totals).
-- cost_micros -> AUD via /1e6 (the RAW DTS metric is micros, unlike the perf_google_ads bridge).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.ga_audience` AS
WITH age AS (
  SELECT 'age' AS dim,
    CASE ad_group_criterion_criterion_id
      WHEN 503001 THEN '18-24' WHEN 503002 THEN '25-34' WHEN 503003 THEN '35-44'
      WHEN 503004 THEN '45-54' WHEN 503005 THEN '55-64' WHEN 503006 THEN '65+'
      ELSE 'Undetermined' END                       AS bucket,
    SUM(metrics_impressions)                        AS imps,
    SUM(metrics_clicks)                             AS clicks,
    ROUND(SUM(metrics_cost_micros) / 1e6, 2)        AS spend_aud,
    ROUND(SUM(metrics_conversions), 1)              AS conversions
  FROM `bidbrain-analytics.raw_google_ads.ads_AgeRangeBasicStats_3451896252`
  WHERE customer_id = 1054407474
  GROUP BY bucket
),
gender AS (
  SELECT 'gender' AS dim,
    CASE ad_group_criterion_criterion_id WHEN 10 THEN 'Male' WHEN 11 THEN 'Female' ELSE 'Undetermined' END AS bucket,
    SUM(metrics_impressions), SUM(metrics_clicks),
    ROUND(SUM(metrics_cost_micros) / 1e6, 2), ROUND(SUM(metrics_conversions), 1)
  FROM `bidbrain-analytics.raw_google_ads.ads_GenderBasicStats_3451896252`
  WHERE customer_id = 1054407474
  GROUP BY bucket
),
device AS (
  SELECT 'device' AS dim,
    INITCAP(REPLACE(segments_device, '_', ' '))     AS bucket,   -- MOBILE->Mobile, CONNECTED_TV->Connected Tv
    SUM(metrics_impressions), SUM(metrics_clicks),
    ROUND(SUM(metrics_cost_micros) / 1e6, 2), ROUND(SUM(metrics_conversions), 1)
  FROM `bidbrain-analytics.raw_google_ads.ads_AgeRangeBasicStats_3451896252`
  WHERE customer_id = 1054407474
  GROUP BY bucket
)
SELECT * FROM (
  SELECT * FROM age UNION ALL SELECT * FROM gender UNION ALL SELECT * FROM device
)
WHERE imps > 0
ORDER BY dim, imps DESC;
