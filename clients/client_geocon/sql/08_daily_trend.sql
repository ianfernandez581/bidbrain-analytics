-- 08_daily_trend: daily series for the CPL-over-time hero chart + cumulative leads.
-- One row per date. cum_leads / cum_spend are running totals across the whole window so the
-- UI can draw the cumulative-leads-vs-target line.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.daily_trend` AS
WITH daily AS (
  SELECT
    date,
    SUM(spend)              AS spend,
    SUM(impressions)        AS impressions,
    SUM(clicks)             AS clicks,
    SUM(link_clicks)        AS link_clicks,
    SUM(landing_page_views) AS landing_page_views,
    SUM(leads)              AS leads,
    SUM(reach)              AS reach
  FROM `bidbrain-analytics.client_geocon.geocon_daily`
  GROUP BY date
)
SELECT
  date,
  spend,
  impressions,
  clicks,
  link_clicks,
  landing_page_views,
  leads,
  reach,
  -- derived daily metrics
  link_clicks / NULLIF(impressions, 0)        AS ctr,
  spend        / NULLIF(impressions, 0) * 1000 AS cpm,
  spend        / NULLIF(link_clicks, 0)        AS cpc,
  spend        / NULLIF(leads, 0)              AS cpl,
  impressions  / NULLIF(reach, 0)              AS frequency,
  -- 7-day rolling CPL: sum(spend) over the window / sum(leads) over the window.
  -- A weighted (not simple) average so a high-spend day counts more than a 1-lead day --
  -- avoids the thin-volume day-to-day noise the May report flagged.
  SUM(spend) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
    / NULLIF(SUM(leads) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 0) AS cpl_7d,
  -- running totals (cumulative across whole window)
  SUM(spend) OVER (ORDER BY date) AS cum_spend,
  SUM(leads) OVER (ORDER BY date) AS cum_leads
FROM daily