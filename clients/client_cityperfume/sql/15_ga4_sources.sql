-- City Perfume — top GA4 source/mediums by sessions (Website tab). is_paid flags the ad
-- sources (any row in this source/medium bucketed Paid — e.g. google/cpc, fb/paid,
-- ig/paid). Top 25 by sessions. Caveat: GA4 degraded from Oct 2025.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.ga4_sources` AS
SELECT
  source_medium,
  LOGICAL_OR(channel_bucket = 'Paid')  AS is_paid,
  SUM(sessions)                        AS sessions,
  SUM(engaged_sessions)                AS engaged_sessions,
  SUM(transactions)                    AS transactions,
  SUM(purchase_revenue)                AS purchase_revenue
FROM `bidbrain-analytics.client_cityperfume.stg_ga4`
GROUP BY source_medium
ORDER BY sessions DESC
LIMIT 25;
