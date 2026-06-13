-- City Perfume — GA4 acquisition staging (filter the shared raw layer once, here).
--
-- Source: bidbrain-analytics.raw_ga4.perf_ga4, account_name='City Perfume'.
-- Session x source/medium x channel-group daily grain. No currency column — values are
-- AUD by assumption (AU retailer). Reporting window 2025-01-01 -> latest applied here.
--
-- DATA-QUALITY CAVEAT: GA4 tracking is BROKEN from ~Oct 2025 (row counts collapse from
-- ~2,500/mo to <120/mo, purchase_revenue/transactions go null). GA4 is only reliable
-- Jun-Sep 2025. The dashboard surfaces GA4 with a visible "tracking degraded from Oct
-- 2025" note and leans on the healthy window; GA4 is NEVER used as a revenue source of
-- truth (v_sales is). Kept windowed/aligned so the break is visible rather than hidden.
--
-- channel_bucket folds the 16 GA4 channel groups into 6 coarse buckets. IMPORTANT:
-- 'Cross-network' = Performance Max / cross-network ads = PAID (it is the single largest
-- group) — do not let it fall into Other.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.stg_ga4` AS
SELECT
  metric_date,
  session_source_medium             AS source_medium,
  session_default_channel_group     AS channel_group,
  CASE
    WHEN session_default_channel_group IN (
      'Cross-network', 'Paid Search', 'Paid Social', 'Paid Shopping',
      'Paid Video', 'Paid Other', 'Display'
    )                                                          THEN 'Paid'
    WHEN session_default_channel_group IN (
      'Organic Search', 'Organic Social', 'Organic Shopping', 'Organic Video'
    )                                                          THEN 'Organic'
    WHEN session_default_channel_group = 'Direct'              THEN 'Direct'
    WHEN session_default_channel_group IN ('Referral', 'Affiliates') THEN 'Referral'
    WHEN session_default_channel_group = 'Email'               THEN 'Email'
    ELSE 'Other'
  END                               AS channel_bucket,
  sessions,
  engaged_sessions,
  total_users,
  new_users,
  transactions,
  purchase_revenue,
  ecommerce_purchases
FROM `bidbrain-analytics.raw_ga4.perf_ga4`
WHERE account_name = 'City Perfume'
  AND metric_date >= DATE '2025-01-01';
