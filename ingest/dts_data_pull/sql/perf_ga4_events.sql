CREATE OR REPLACE VIEW `bidbrain-analytics.raw_ga4.perf_ga4_events` AS
SELECT * EXCEPT(_arm) REPLACE (
  CASE property_id WHEN '254028250' THEN 'city-perfume' WHEN '516276493' THEN 'reset-data' WHEN '318963196' THEN 'stt-gdc-web-all' WHEN '434839993' THEN 'stt-gdc-web-global' WHEN '413451542' THEN 'stt-gdc-web-india' WHEN '413487460' THEN 'stt-gdc-web-indonesia' WHEN '434829327' THEN 'stt-gdc-web-japan' WHEN '434854278' THEN 'stt-gdc-web-korea' WHEN '434905821' THEN 'stt-gdc-web-malaysia' WHEN '413491455' THEN 'stt-gdc-web-philippines' WHEN '413490347' THEN 'stt-gdc-web-singapore' WHEN '413495845' THEN 'stt-gdc-web-thailand' WHEN '434852571' THEN 'stt-gdc-web-vietnam' WHEN '273098216' THEN 'atlantis-reservations' WHEN '506931798' THEN 'chocolategrove' WHEN '468621509' THEN 'sophiie' WHEN '287370621' THEN 'vmch-website-ga4' WHEN '341832593' THEN 'http-atlantisevents-com-ga4' WHEN '341827046' THEN 'http-rsvpvacations-com-ga4' WHEN '358885683' THEN 'https-100-digital' ELSE client_slug END AS client_slug,
  '100-digital' AS agency_slug
)
FROM (
  SELECT * FROM (
    SELECT *, 0 AS _arm FROM (
SELECT
  '254028250'                              AS property_id,
  'city-perfume'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_254028250` t
UNION ALL
SELECT
  '318963196'                              AS property_id,
  'stt-gdc-web-all'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_318963196` t
UNION ALL
SELECT
  '413451542'                              AS property_id,
  'stt-gdc-web-india'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_413451542` t
UNION ALL
SELECT
  '413487460'                              AS property_id,
  'stt-gdc-web-indonesia'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_413487460` t
UNION ALL
SELECT
  '413490347'                              AS property_id,
  'stt-gdc-web-singapore'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_413490347` t
UNION ALL
SELECT
  '413491455'                              AS property_id,
  'stt-gdc-web-philippines'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_413491455` t
UNION ALL
SELECT
  '413495845'                              AS property_id,
  'stt-gdc-web-thailand'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_413495845` t
UNION ALL
SELECT
  '434829327'                              AS property_id,
  'stt-gdc-web-japan'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_434829327` t
UNION ALL
SELECT
  '434839993'                              AS property_id,
  'stt-gdc-web-global'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_434839993` t
UNION ALL
SELECT
  '434852571'                              AS property_id,
  'stt-gdc-web-vietnam'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_434852571` t
UNION ALL
SELECT
  '434854278'                              AS property_id,
  'stt-gdc-web-korea'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_434854278` t
UNION ALL
SELECT
  '434905821'                              AS property_id,
  'stt-gdc-web-malaysia'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_434905821` t
UNION ALL
SELECT
  '516276493'                              AS property_id,
  'reset-data'                         AS client_slug,
  '100-digital'                         AS agency_slug,
  t._DATA_DATE                          AS metric_date,
  t.eventName                           AS event_name,
  CAST(NULL AS BOOL)                    AS is_conversion_event,
  t.eventCount                          AS event_count,
  t.totalRevenue                        AS event_value,
  CAST(NULL AS FLOAT64)                 AS conversions,
  TO_JSON(t)                            AS raw_row,
  CURRENT_TIMESTAMP()                   AS _loaded_at
FROM `bidbrain-analytics.raw_ga4.ga4_Events_516276493` t
    )
    UNION ALL
    SELECT *, 1 AS _arm FROM `bidbrain-analytics.raw_windsor.perf_ga4_events`
  )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY property_id, metric_date, event_name
    ORDER BY _arm
  ) = 1
);
