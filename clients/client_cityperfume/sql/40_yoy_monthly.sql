-- City Perfume — YEAR-ON-YEAR monthly comparison (the finance "Year on Year" tab).
-- Pairs each month with the SAME calendar month one year earlier, in plain AUD dollars
-- plus the YoY growth %, for ad spend, revenue (total + online), margin, orders and the
-- blended ROAS. Built by self-joining the `monthly` rollup on month = prior-year month,
-- so it inherits monthly's FULL OUTER JOIN coverage (a month with sales but no ads, or
-- vice-versa, still appears) and its definitions stay single-sourced.
--
-- Data availability (CURRENT pipeline — no client tracker baseline yet): first-party
-- sales AND total ad spend both run from 2025-01, so every 2026 month has a real 2025
-- comparison. Months with no prior-year row get NULL *_py / *_yoy (rendered as "no
-- comparison"). The newest month is the in-progress current month (partial); the
-- dashboard flags it and excludes it from year-to-date totals.
--
-- NOTE (flagged to client): the prior-year baseline here is our own first-party v_sales,
-- NOT City Perfume's old sales tracker. When Thanh provides the tracker figures we can
-- swap/reconcile the *_py revenue source without touching the dashboard.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cityperfume.yoy_monthly` AS
SELECT
  cur.month,
  EXTRACT(YEAR  FROM cur.month) AS year,
  EXTRACT(MONTH FROM cur.month) AS month_num,
  -- current year (AUD)
  cur.revenue_total,
  cur.revenue_online,
  cur.ad_spend,
  cur.margin,
  cur.orders,
  cur.roas_blended,
  cur.roas_online,
  -- prior year, same calendar month (AUD)
  prev.revenue_total  AS revenue_total_py,
  prev.revenue_online AS revenue_online_py,
  prev.ad_spend       AS ad_spend_py,
  prev.margin         AS margin_py,
  prev.orders         AS orders_py,
  prev.roas_blended   AS roas_blended_py,
  prev.roas_online    AS roas_online_py,
  -- YoY growth (NULL when no prior-year month exists)
  SAFE_DIVIDE(cur.revenue_total  - prev.revenue_total,  prev.revenue_total)  AS revenue_total_yoy,
  SAFE_DIVIDE(cur.revenue_online - prev.revenue_online, prev.revenue_online) AS revenue_online_yoy,
  SAFE_DIVIDE(cur.ad_spend       - prev.ad_spend,       prev.ad_spend)       AS ad_spend_yoy,
  SAFE_DIVIDE(cur.margin         - prev.margin,         prev.margin)         AS margin_yoy,
  SAFE_DIVIDE(cur.orders         - prev.orders,         prev.orders)         AS orders_yoy
FROM `bidbrain-analytics.client_cityperfume.monthly` cur
LEFT JOIN `bidbrain-analytics.client_cityperfume.monthly` prev
  ON prev.month = DATE_SUB(cur.month, INTERVAL 1 YEAR)
ORDER BY cur.month;
