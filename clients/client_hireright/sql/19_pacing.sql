-- HireRight - pacing: planned vs delivered, per platform. One row per platform that
-- either has a plan line or has delivered, so a platform running WITHOUT a plan line
-- is visible (as target NULL) rather than silently missing.
--
-- THREE THINGS THIS VIEW IS CAREFUL ABOUT
--
-- 1. NULL target != zero target. A blank cell in the media plan means the plan does
--    not commit to that metric. Every `*_pct` below is NULL when its target is NULL,
--    so the dashboard can omit the metric instead of drawing a 0% miss against a KPI
--    nobody bought.
--
-- 2. "Pace to date" is NOT the same as "% of target". A flight that is 40% elapsed and
--    has delivered 38% of its impressions is ON pace, even though attainment reads 38%.
--    Both are emitted: `*_pct` (of the whole commitment) and `*_pace` (against the even
--    flight pace to date). Reporting only the first makes every live campaign look like
--    it is failing. Repo precedent: client_schneider's scorecard, which had to have this
--    distinction spelled out in a column tooltip.
--
-- 3. Flight dates may be absent. An unsigned plan has no dates, so the flight falls back
--    to OBSERVED first/last delivery and `flight_source` says which it is. The dashboard
--    must print "live since" for an observed flight, never "flight" - claiming a booked
--    window that does not exist is the kind of thing a client notices.
--
-- `has_targets` is carried on every row so a single read tells the job whether ANY real
-- commitment exists; when it is FALSE the dashboard hides the whole pacing section.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.pacing` AS
WITH
-- One plan row per platform. If a plan ever buys several line items per platform, they
-- are summed here for the platform-level card (volumes add; the efficiency targets are
-- taken as the volume-weighted intent via a simple MIN/MAX-free AVG of the stated ones).
plan AS (
  SELECT
    platform,
    MIN(flight_start)   AS flight_start,
    MAX(flight_end)     AS flight_end,
    SUM(budget_usd)     AS budget_usd,
    SUM(imp_target)     AS imp_target,
    SUM(click_target)   AS click_target,
    SUM(lead_target)    AS lead_target,
    AVG(ctr_target)     AS ctr_target,
    AVG(cpm_target_usd) AS cpm_target_usd,
    AVG(cpc_target_usd) AS cpc_target_usd,
    COUNT(*)            AS plan_lines
  FROM `bidbrain-analytics.client_hireright.targets`
  GROUP BY platform
),
act AS (
  SELECT
    platform,
    SUM(imps)         AS imps,
    SUM(clicks)       AS clicks,
    SUM(spend_usd)    AS spend_usd,
    SUM(leads)        AS leads,
    SUM(attr_conv)    AS attr_conv,
    MIN(metric_date)  AS first_day,
    MAX(metric_date)  AS last_day
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform
),
j AS (
  SELECT
    COALESCE(p.platform, a.platform) AS platform,
    p.plan_lines,
    -- Flight = the booked window when the plan states one, else what actually delivered.
    COALESCE(p.flight_start, a.first_day) AS flight_start,
    COALESCE(p.flight_end,   a.last_day)  AS flight_end,
    CASE WHEN p.flight_start IS NOT NULL THEN 'planned' ELSE 'observed' END AS flight_source,
    p.budget_usd, p.imp_target, p.click_target, p.lead_target,
    p.ctr_target, p.cpm_target_usd, p.cpc_target_usd,
    IFNULL(a.imps, 0)      AS imps,
    IFNULL(a.clicks, 0)    AS clicks,
    IFNULL(a.spend_usd, 0) AS spend_usd,
    IFNULL(a.leads, 0)     AS leads,
    IFNULL(a.attr_conv, 0) AS attr_conv,
    a.first_day, a.last_day
  FROM plan p
  FULL OUTER JOIN act a USING (platform)
),
e AS (
  SELECT
    *,
    -- Share of the flight elapsed as of today, clamped to [0,1]. A flight that has not
    -- started yet is 0 (not negative); a finished one is 1 (not >1).
    CASE
      WHEN flight_start IS NULL OR flight_end IS NULL OR flight_end < flight_start THEN NULL
      ELSE LEAST(1.0, GREATEST(0.0,
        SAFE_DIVIDE(
          DATE_DIFF(LEAST(CURRENT_DATE(), flight_end), flight_start, DAY) + 1,
          DATE_DIFF(flight_end, flight_start, DAY) + 1)))
    END AS elapsed_frac
  FROM j
)
SELECT
  platform,
  IFNULL(plan_lines, 0) AS plan_lines,
  flight_start, flight_end, flight_source, elapsed_frac,
  budget_usd, imp_target, click_target, lead_target,
  ctr_target, cpm_target_usd, cpc_target_usd,
  imps, clicks, spend_usd, leads, attr_conv,
  first_day, last_day,
  -- Attainment: delivered / whole commitment. NULL when nothing was committed.
  SAFE_DIVIDE(spend_usd, budget_usd)  AS spend_pct,
  SAFE_DIVIDE(imps,      imp_target)  AS imp_pct,
  SAFE_DIVIDE(clicks,    click_target) AS click_pct,
  SAFE_DIVIDE(leads,     lead_target) AS lead_pct,
  -- Pace: attainment divided by the share of flight elapsed. 1.0 = exactly on the even
  -- flight pace, >1 ahead, <1 behind. NULL when there is no target or no dated flight.
  SAFE_DIVIDE(SAFE_DIVIDE(spend_usd, budget_usd),  elapsed_frac) AS spend_pace,
  SAFE_DIVIDE(SAFE_DIVIDE(imps,      imp_target),  elapsed_frac) AS imp_pace,
  SAFE_DIVIDE(SAFE_DIVIDE(clicks,    click_target), elapsed_frac) AS click_pace,
  SAFE_DIVIDE(SAFE_DIVIDE(leads,     lead_target), elapsed_frac) AS lead_pace,
  -- TRUE if ANY platform carries any real commitment - drives the dashboard's
  -- show/hide of the entire pacing section.
  (SELECT LOGICAL_OR(budget_usd IS NOT NULL OR imp_target IS NOT NULL
                     OR click_target IS NOT NULL OR lead_target IS NOT NULL)
     FROM `bidbrain-analytics.client_hireright.targets`) AS has_targets
FROM e
ORDER BY spend_usd DESC;
