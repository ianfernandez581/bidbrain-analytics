-- 05_overview: totals + current-flight pacing. Single row. job/main.py reads this.
-- Flight is 21 Jun - 20 Jul 2026 (from the budget seed); pacing expected = daily_pace * days_elapsed.
-- daily_pace and targets come from the seed (Phase 3). Joins targets so the UI target lines are
-- data-driven, not hard-coded.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.overview` AS
WITH totals AS (
  SELECT
    SUM(spend)              AS spend,
    SUM(impressions)        AS impressions,
    SUM(reach)              AS reach,
    SUM(clicks)             AS clicks,
    SUM(link_clicks)        AS link_clicks,
    SUM(landing_page_views) AS landing_page_views,
    SUM(leads)              AS leads,
    MIN(date)               AS date_start,
    MAX(date)               AS date_end,
    MAX(currency)           AS currency
  FROM `bidbrain-analytics.client_geocon.geocon_daily`
),
tgt AS (
  -- value is STRING in the seed (numbers + dates); cast the numeric ones here.
  SELECT
    SAFE_CAST(MAX(IF(key='flight_budget_aud',        value, NULL)) AS FLOAT64) AS flight_budget_aud,
    SAFE_CAST(MAX(IF(key='daily_pace_aud',           value, NULL)) AS FLOAT64) AS daily_pace_aud,
    SAFE_CAST(MAX(IF(key='cpl_target_aud',           value, NULL)) AS FLOAT64) AS cpl_target_aud,
    SAFE_CAST(MAX(IF(key='ctr_target',               value, NULL)) AS FLOAT64) AS ctr_target,
    SAFE_CAST(MAX(IF(key='cpm_target_aud',           value, NULL)) AS FLOAT64) AS cpm_target_aud,
    SAFE_CAST(MAX(IF(key='cpc_target_aud',           value, NULL)) AS FLOAT64) AS cpc_target_aud,
    SAFE_CAST(MAX(IF(key='cost_per_lpv_target_aud',  value, NULL)) AS FLOAT64) AS cost_per_lpv_target_aud,
    SAFE_CAST(MAX(IF(key='monthly_lead_target',      value, NULL)) AS FLOAT64) AS monthly_lead_target
  FROM `bidbrain-analytics.client_geocon.targets`
),
bud AS (
  SELECT
    CAST(flight_start AS DATE) AS flight_start,
    CAST(flight_end   AS DATE) AS flight_end,
    budget_aud
  FROM `bidbrain-analytics.client_geocon.budget`
  WHERE campaign_key = 'GATEWAY'
  LIMIT 1
)
SELECT
  t.spend,
  t.impressions,
  t.reach,
  t.clicks,
  t.link_clicks,
  t.landing_page_views,
  t.leads,
  t.date_start,
  t.date_end,
  t.currency,
  -- derived (divide-by-zero safe)
  t.link_clicks  / NULLIF(t.impressions, 0)        AS ctr,
  t.clicks       / NULLIF(t.impressions, 0)        AS ctr_all,
  t.spend        / NULLIF(t.impressions, 0) * 1000 AS cpm,
  t.spend        / NULLIF(t.link_clicks, 0)        AS cpc,
  t.spend        / NULLIF(t.leads, 0)              AS cpl,
  t.spend        / NULLIF(t.landing_page_views, 0) AS cost_per_lpv,
  t.impressions  / NULLIF(t.reach, 0)              AS frequency,
  -- flight pacing
  b.flight_start,
  b.flight_end,
  b.budget_aud,
  DATE_DIFF(CURRENT_DATE(), b.flight_start, DAY) + 1                        AS days_elapsed,
  DATE_DIFF(b.flight_end, b.flight_start, DAY) + 1                          AS days_total,
  g.daily_pace_aud * (DATE_DIFF(CURRENT_DATE(), b.flight_start, DAY) + 1)   AS pace_expected,
  -- projected end-of-flight spend at current run-rate
  SAFE_DIVIDE(t.spend, DATE_DIFF(CURRENT_DATE(), b.flight_start, DAY) + 1)
    * (DATE_DIFF(b.flight_end, b.flight_start, DAY) + 1)                    AS projected_spend,
  -- targets (joined for data-driven UI lines)
  g.flight_budget_aud, g.daily_pace_aud, g.cpl_target_aud, g.ctr_target,
  g.cpm_target_aud, g.cpc_target_aud, g.cost_per_lpv_target_aud, g.monthly_lead_target
FROM totals t
CROSS JOIN tgt g
CROSS JOIN bud b