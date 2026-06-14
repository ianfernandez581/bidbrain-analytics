-- TLM — headline KPI row (the single row the dashboard reads for the big numbers).
--
-- E-commerce "ads → revenue / ROAS": Google Ads delivery + conversions/revenue alongside
-- Trade Desk delivery only. Google is the revenue source (conversions_value = revenue AUD;
-- conversions = purchases). TTD contributes spend/impressions/clicks but no conversions
-- or revenue (pixel fires are anonymous). Window = 2025-08-01 → latest metric_date across
-- both platforms. FX_USD_AUD (1.50) kept for completeness (TTD EDA shows AUD already,
-- but the CASE is present in stg_ttd for robustness). ad_* = Google + TTD combined.
-- ROAS / AOV / CPA are derived client-side, never stored here.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.kpi` AS
WITH
g AS (
  SELECT
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    SUM(conversions) AS conversions,
    SUM(revenue)     AS revenue,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_tlm.stg_google`
),
td AS (
  SELECT
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_aud)   AS spend_aud,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_tlm.stg_ttd`
)
SELECT
  1.50 AS fx_usd_aud,
  DATE '2025-08-01'     AS campaign_start,           -- first-of-month of Google min 2025-08-05
  GREATEST(g.end_date, IFNULL(td.end_date, g.end_date)) AS campaign_end,
  DATE_DIFF(GREATEST(g.end_date, IFNULL(td.end_date, g.end_date)), DATE '2025-08-01', DAY) + 1 AS campaign_days,
  -- Google Ads
  g.imps        AS g_imps,
  g.clicks      AS g_clicks,
  g.spend_aud   AS g_spend_aud,
  g.conversions AS g_conv,
  g.revenue     AS g_revenue,
  g.start_date  AS g_start,
  g.end_date    AS g_end,
  -- Trade Desk
  IFNULL(td.imps, 0)      AS t_imps,
  IFNULL(td.clicks, 0)    AS t_clicks,
  IFNULL(td.spend_aud, 0) AS t_spend_aud,
  td.start_date           AS t_start,
  td.end_date             AS t_end,
  -- Combined ad delivery
  (g.imps       + IFNULL(td.imps, 0))      AS ad_imps,
  (g.clicks     + IFNULL(td.clicks, 0))    AS ad_clicks,
  (g.spend_aud  + IFNULL(td.spend_aud, 0)) AS ad_spend_aud,
  -- conversions + revenue are Google-only (TTD has none)
  g.conversions AS conversions,
  g.revenue     AS revenue
FROM g, td;