-- Secure Power unified paid-media delivery fact — the dashboard's main data source.
--
-- One row per campaign × platform × market × day (the `pm_delivery` analog). The dashboard
-- aggregates this client-side: hero time-series, campaign comparison, market breakdown — filtered by
-- the campaign chips, market chips, platform chips and the date-range picker.
--
-- AGGREGATED on purpose. The staging views are at ad-set/ad-group/creative grain and this view
-- exposes no such column, so an ungrouped SELECT would emit one duplicate row per delivering ad group
-- that every consumer would sum anyway - the exact defect that once blew client_schneider's payload to
-- 13.6 MB. If a finer grain is ever needed, add a SEPARATE view rather than un-grouping this one.
--
-- `region` rolls the fine markets up to the four reporting regions these three briefs run in, so the
-- Overview can show a regional split without losing the AU/NZ detail underneath. Note Pacific covers
-- Australia, New Zealand, the combined 'ANZ' residual AND Enterprise IT's own 'Pacific' token.
--
-- SUM(leads)/SUM(lead_form_opens) over an all-NULL Trade Desk group returns NULL, not 0, so the
-- dashboard can auto-hide the LinkedIn-only lead-form metric instead of drawing a false zero.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneidersecpwr.delivery` AS
WITH u AS (
  SELECT campaign, platform, metric_date, market, imps, clicks, spend_aud, leads, lead_form_opens
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_linkedin`
  UNION ALL
  SELECT campaign, platform, metric_date, market, imps, clicks, spend_aud, leads, lead_form_opens
  FROM `bidbrain-analytics.client_schneidersecpwr.stg_tradedesk`
)
SELECT
  campaign,
  platform,
  metric_date,
  market,
  CASE market
    WHEN 'Australia'     THEN 'Pacific'
    WHEN 'New Zealand'   THEN 'Pacific'
    WHEN 'ANZ'           THEN 'Pacific'
    WHEN 'Pacific'       THEN 'Pacific'
    WHEN 'India'         THEN 'India'
    WHEN 'MEA'           THEN 'MEA'
    WHEN 'South America' THEN 'South America'
    ELSE 'Other'
  END                                      AS region,
  SUM(imps)                                AS imps,
  SUM(clicks)                              AS clicks,
  SUM(spend_aud)                           AS spend_aud,
  SUM(leads)                               AS leads,
  SUM(lead_form_opens)                     AS lead_form_opens
FROM u
GROUP BY campaign, platform, metric_date, market, region;
