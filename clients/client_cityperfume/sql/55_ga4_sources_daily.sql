-- City Perfume — GA4 source/medium per DAY (range-aware source for the top-sources table).
-- Ships the full-period top 30 sources by sessions, at day grain; the dashboard clips to the
-- range, re-aggregates per source, and shows the top sources over the window. is_paid is OR-ed
-- across the day's rows. Additive columns only. Caveat: GA4 degraded from ~Oct 2025.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_sources_daily` AS
WITH pool AS (
  SELECT source_medium
  FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
  GROUP BY source_medium
  ORDER BY SUM(sessions) DESC
  LIMIT 30
)
SELECT
  metric_date                          AS day,
  source_medium,
  LOGICAL_OR(channel_bucket = 'Paid')  AS is_paid,
  SUM(sessions)                        AS sessions,
  SUM(engaged_sessions)                AS engaged_sessions,
  SUM(transactions)                    AS transactions,
  SUM(purchase_revenue)                AS purchase_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
WHERE source_medium IN (SELECT source_medium FROM pool)
GROUP BY day, source_medium
ORDER BY day, sessions DESC;
