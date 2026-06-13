-- HireRight - headline KPI row (single row the dashboard reads for the FX rate,
-- the reporting window and the whole-flight per-platform / blended totals).
--
-- Pure paid-media delivery (no GA4 / website side). Reporting currency = USD; each
-- stg_* view already converted its spend, so the totals just sum. FX_AUD_USD (0.65)
-- is surfaced as fx_aud_usd. The window is the data span across all three platforms
-- (no fixed campaign start - see the brief: "the window is the data span"). ad_* =
-- DV360 + TradeDesk + LinkedIn combined.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.kpi` AS
WITH
dv AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_usd) AS spend_usd,
         SUM(conversions) AS conv, MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_dv360`
),
td AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_usd) AS spend_usd,
         SUM(conversions) AS conv, MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_tradedesk`
),
li AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(cost_usd) AS cost_usd,
         SUM(leads) AS conv, MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_linkedin`
)
SELECT
  0.65 AS fx_aud_usd,
  -- Reporting window = earliest -> latest delivery day across all platforms.
  LEAST(
    COALESCE(dv.start_date, DATE '9999-12-31'),
    COALESCE(td.start_date, DATE '9999-12-31'),
    COALESCE(li.start_date, DATE '9999-12-31')
  ) AS campaign_start,
  GREATEST(
    COALESCE(dv.end_date, DATE '0001-01-01'),
    COALESCE(td.end_date, DATE '0001-01-01'),
    COALESCE(li.end_date, DATE '0001-01-01')
  ) AS campaign_end,
  DATE_DIFF(
    GREATEST(COALESCE(dv.end_date, DATE '0001-01-01'), COALESCE(td.end_date, DATE '0001-01-01'), COALESCE(li.end_date, DATE '0001-01-01')),
    LEAST(COALESCE(dv.start_date, DATE '9999-12-31'), COALESCE(td.start_date, DATE '9999-12-31'), COALESCE(li.start_date, DATE '9999-12-31')),
    DAY
  ) + 1 AS campaign_days,
  dv.start_date AS dv_start, dv.end_date AS dv_end,
  td.start_date AS td_start, td.end_date AS td_end,
  li.start_date AS li_start, li.end_date AS li_end,
  dv.imps AS dv_imps, dv.clicks AS dv_clicks, dv.spend_usd AS dv_spend_usd, dv.conv AS dv_conv,
  td.imps AS td_imps, td.clicks AS td_clicks, td.spend_usd AS td_spend_usd, td.conv AS td_conv,
  li.imps AS li_imps, li.clicks AS li_clicks, li.cost_usd AS li_cost_usd, li.conv AS li_conv,
  (IFNULL(dv.imps,0)      + IFNULL(td.imps,0)      + IFNULL(li.imps,0))      AS ad_imps,
  (IFNULL(dv.clicks,0)    + IFNULL(td.clicks,0)    + IFNULL(li.clicks,0))    AS ad_clicks,
  (IFNULL(dv.spend_usd,0) + IFNULL(td.spend_usd,0) + IFNULL(li.cost_usd,0))  AS ad_spend_usd,
  (IFNULL(dv.conv,0)      + IFNULL(td.conv,0)      + IFNULL(li.conv,0))      AS ad_conv
FROM dv, td, li;
