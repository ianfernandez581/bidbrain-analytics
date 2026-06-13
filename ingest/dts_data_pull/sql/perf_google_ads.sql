CREATE OR REPLACE VIEW `bidbrain-analytics.raw_google_ads.perf_google_ads` AS
-- Re-derive account_name/client_slug/agency_slug from customer_id so the native and Windsor
-- arms tag CONSISTENTLY. Windsor's customer_id is hyphenated -> normalized to bare digits.
SELECT * REPLACE (
  CASE customer_id WHEN '2617916504' THEN 'City Perfume' WHEN '1054407474' THEN 'Reset Data' WHEN '1869745895' THEN 'The Little Marionette' WHEN '5196596415' THEN 'Liberty' WHEN '8509313407' THEN 'Paradise' ELSE account_name END AS account_name,
  CASE customer_id WHEN '2617916504' THEN 'city-perfume' WHEN '1054407474' THEN 'reset-data' WHEN '1869745895' THEN 'the-little-marionette' WHEN '5196596415' THEN 'liberty' WHEN '8509313407' THEN 'paradise' ELSE client_slug END AS client_slug,
  '100-digital' AS agency_slug
)
FROM (
  SELECT * FROM (
SELECT
  'google_ads'                          AS platform,
  CAST(s.customer_id AS STRING)         AS customer_id,
  cust.customer_descriptive_name        AS account_name,
  COALESCE(NULLIF(LOWER(TRIM(REGEXP_REPLACE(cust.customer_descriptive_name, r'[^A-Za-z0-9]+', '-'), '-')), ''), 'unknown') AS client_slug,
  '100-digital' AS agency_slug,
  s.metric_date                         AS metric_date,
  CAST(s.campaign_id AS STRING)         AS campaign_id,
  c.campaign_name                       AS campaign_name,
  c.campaign_advertising_channel_type   AS campaign_type,
  cust.customer_currency_code           AS currency_code,
  s.impressions                         AS impressions,
  s.clicks                              AS clicks,
  s.spend                               AS spend,
  s.conversions                         AS conversions,
  s.conversions_value                   AS conversions_value,
  CURRENT_TIMESTAMP()                   AS ingested_at,
  'dts.google_ads'                      AS source,
  TO_JSON(s)                            AS raw_row
FROM (
  SELECT customer_id, campaign_id, segments_date AS metric_date,
         SUM(metrics_impressions)                        AS impressions,
         SUM(metrics_clicks)                             AS clicks,
         CAST(SUM(metrics_cost_micros) / 1e6 AS NUMERIC) AS spend,
         CAST(SUM(metrics_conversions) AS NUMERIC)       AS conversions,
         CAST(SUM(metrics_conversions_value) AS NUMERIC) AS conversions_value
  FROM `bidbrain-analytics.raw_google_ads.ads_CampaignBasicStats_3451896252`
  GROUP BY customer_id, campaign_id, segments_date
) s
LEFT JOIN (
  SELECT campaign_id, customer_id, campaign_name, campaign_advertising_channel_type
  FROM `bidbrain-analytics.raw_google_ads.ads_Campaign_3451896252`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY campaign_id ORDER BY _DATA_DATE DESC) = 1
) c USING (campaign_id, customer_id)
LEFT JOIN (
  SELECT customer_id, customer_descriptive_name, customer_currency_code
  FROM `bidbrain-analytics.raw_google_ads.ads_Customer_3451896252`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY _DATA_DATE DESC) = 1
) cust USING (customer_id)
    UNION ALL
    SELECT * REPLACE (REGEXP_REPLACE(customer_id, r'[^0-9]', '') AS customer_id)
    FROM `bidbrain-analytics.raw_windsor.perf_google_ads`
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY customer_id, campaign_id, metric_date
    ORDER BY CASE source WHEN 'dts.google_ads' THEN 0 ELSE 1 END
  ) = 1
);
