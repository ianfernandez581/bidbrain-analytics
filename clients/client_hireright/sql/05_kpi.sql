-- HireRight - headline KPI row (single row the dashboard reads for the FX rate,
-- the reporting window and the whole-flight per-platform / blended totals).
--
-- Pure paid-media delivery (no GA4 / website side). Reporting currency = USD; each
-- stg_* view already converted its spend at the shared rate, so the totals just sum.
-- fx_aud_usd is read from the `fx` view (00_fx.sql) rather than re-typed, so what the
-- dashboard PRINTS as the rate is guaranteed to be the rate the spend was converted at.
--
-- The window is the data span across all three platforms (no fixed campaign start -
-- see the brief: "the window is the data span"). Per-platform windows are carried
-- separately because the three feeds do NOT run concurrently, and a platform whose
-- feed has stopped must be readable as stopped.
--
-- OUTCOMES ARE NOT BLENDED. `ad_conv` (DV360 + TTD + LinkedIn leads summed) has been
-- REMOVED - it added post-view display conversions to submitted lead forms. See the
-- long note in 04_stg_ad_delivery.sql. What replaces it:
--   li_leads      - LinkedIn lead-gen form submissions (a real outcome)
--   ad_attr_conv  - DV360 + TTD attributed (post-click + post-view) conversions,
--                   NOT deduplicated between the two platforms
-- Any consumer wanting a single number must choose one of these and label it.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.kpi` AS
WITH
dv AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_usd) AS spend_usd,
         SUM(attr_conv) AS attr_conv, MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_dv360`
),
td AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_usd) AS spend_usd,
         SUM(attr_conv) AS attr_conv, MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_tradedesk`
),
li AS (
  SELECT SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(cost_usd) AS cost_usd,
         SUM(leads) AS leads, SUM(lead_form_opens) AS lead_form_opens,
         MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_linkedin`
)
SELECT
  (SELECT aud_usd FROM `bidbrain-analytics.client_hireright.fx`) AS fx_aud_usd,
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
  dv.imps AS dv_imps, dv.clicks AS dv_clicks, dv.spend_usd AS dv_spend_usd, dv.attr_conv AS dv_attr_conv,
  td.imps AS td_imps, td.clicks AS td_clicks, td.spend_usd AS td_spend_usd, td.attr_conv AS td_attr_conv,
  li.imps AS li_imps, li.clicks AS li_clicks, li.cost_usd AS li_cost_usd,
  li.leads AS li_leads, li.lead_form_opens AS li_lead_form_opens,
  (IFNULL(dv.imps,0)      + IFNULL(td.imps,0)      + IFNULL(li.imps,0))      AS ad_imps,
  (IFNULL(dv.clicks,0)    + IFNULL(td.clicks,0)    + IFNULL(li.clicks,0))    AS ad_clicks,
  (IFNULL(dv.spend_usd,0) + IFNULL(td.spend_usd,0) + IFNULL(li.cost_usd,0))  AS ad_spend_usd,
  -- Programmatic attributed conversions ONLY (DV360 + TTD). LinkedIn leads are NOT
  -- added in - see the header.
  (IFNULL(dv.attr_conv,0) + IFNULL(td.attr_conv,0))                          AS ad_attr_conv
FROM dv, td, li;
