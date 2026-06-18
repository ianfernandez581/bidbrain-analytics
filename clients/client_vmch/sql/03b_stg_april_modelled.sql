-- VMCH — MODELLED April 2026 delivery for RAC + SAH (synthetic, flat daily).
--
-- WHY THIS EXISTS: The Trade Desk's full April delivery for the RAC (Residential Aged
-- Care) and SAH (Seniors at Home) campaigns never landed in the Windsor feed — only
-- stray Apr-30 slivers did (RAC 16k imps / A$38, SAH 7 imps / A$0.10). The client
-- supplied April's real campaign totals, so we simulate the month by spreading each
-- monthly total evenly across all 30 days (total ÷ 30 per day, per the client's request):
--
--   RAC : 1,251,220 imps · 3,809 clicks · A$4,678.58   (Aged Care - RAC)
--   SAH : 3,050,621 imps · 2,772 clicks · A$7,041.63   (Aged Care - SAH)
--
-- This is MODELLED, not measured. It is unioned into stg_ad_delivery (03c) — which also
-- DROPS the real Apr-30 RAC/SAH slivers so there is no double count — and therefore flows
-- into every campaign-grained roll-up + the time-series/KPI views (which 04/05/12/30 now
-- read from stg_ad_delivery). It deliberately does NOT touch stg_ttd, so the whole-flight
-- ad-group / creative breakdowns (ttd_adgroups, ttd_creative) stay pure measured TTD data
-- — we have no ad-group/creative granularity for the modelled month. Disability ran for
-- real in April and is untouched. post_view/post_click = 0 (no attributed conversions in
-- the client's April figures). Output columns match stg_ad_delivery EXACTLY (for the UNION).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_april_modelled` AS
WITH spec AS (
  SELECT * FROM UNNEST([
    STRUCT('RAC_AU_ID Digital_VMCH_2026' AS campaign, 1251220 AS m_imps, 3809 AS m_clicks, NUMERIC '4678.58' AS m_spend),
    STRUCT('SAH_AU_ID Digital_VMCH_2026' AS campaign, 3050621 AS m_imps, 2772 AS m_clicks, NUMERIC '7041.63' AS m_spend)
  ])
),
days AS (
  SELECT d AS metric_date
  FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-04-01', DATE '2026-04-30')) AS d
)
SELECT
  'ttd'                                           AS platform,
  spec.campaign                                   AS campaign,
  days.metric_date                                AS metric_date,
  CAST(NULL AS STRING)                            AS market,
  CAST(NULL AS STRING)                            AS ad_group_name,
  CAST(NULL AS STRING)                            AS creative_name,
  CAST(ROUND(spec.m_imps   / 30) AS INT64)        AS imps,
  CAST(ROUND(spec.m_clicks / 30) AS INT64)        AS clicks,
  CAST(spec.m_spend / 30 AS NUMERIC)              AS spend_aud,
  CAST(0 AS FLOAT64)                              AS post_view_conv,
  CAST(0 AS FLOAT64)                              AS post_click_conv
FROM days CROSS JOIN spec;
