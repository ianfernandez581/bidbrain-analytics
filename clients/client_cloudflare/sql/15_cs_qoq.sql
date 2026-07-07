-- Cloudflare — Content-Syndication QUARTER-ON-QUARTER, QUARTER-TO-DATE aligned (Q3 vs Q2), ACTUALS ONLY.
-- Client asked (2026-07) to compare the new quarter (Q3, Jul-Sep) to the prior (Q2, Apr-Jun) — but a
-- fair comparison at the START of Q3 must be LIKE-FOR-LIKE: Q3-to-date vs Q2 through the SAME number of
-- days into the quarter (not Q3's first few days against all of Q2). So we align on day-of-quarter:
--   asof_day_idx = the latest day-of-quarter present in Q3 (0-based; Jul 1 = 0).
--   leads_qtd    = leads whose day-of-quarter <= asof_day_idx  -> Q3 QTD, and Q2's SAME opening window.
--   leads_full   = whole-quarter count (Q2's full total, kept as context; for Q3 it equals QTD).
-- Built on salesforce_leads_live so it reuses the exact accepted-lead + market logic (REGION_GRP = the
-- COARSE 7 chips as of 2026-07-07, OTHER excluded; accepted = Accepted/Replied/Unresponsive; Transmission
-- test leads already dropped upstream). Calendar quarters. No Q3 targets loaded yet, so this is
-- actuals-vs-actuals (no pacing here). Grain: (quarter, market, status_bucket).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_qoq` AS
WITH tagged AS (
  SELECT
    CASE WHEN DAY BETWEEN DATE '2026-04-01' AND DATE '2026-06-30' THEN 'Q2'
         WHEN DAY BETWEEN DATE '2026-07-01' AND DATE '2026-09-30' THEN 'Q3' END AS quarter,
    CASE WHEN DAY BETWEEN DATE '2026-04-01' AND DATE '2026-06-30' THEN DATE_DIFF(DAY, DATE '2026-04-01', DAY)
         WHEN DAY BETWEEN DATE '2026-07-01' AND DATE '2026-09-30' THEN DATE_DIFF(DAY, DATE '2026-07-01', DAY)
    END AS day_idx,                                    -- 0-based day-of-quarter
    REGION_GRP AS market,
    CASE
      WHEN LEAD_STATUS IN ('Accepted', 'Replied', 'Unresponsive') THEN 'Accepted'
      WHEN LEAD_STATUS = 'Rejected'                               THEN 'Rejected'
      WHEN LEAD_STATUS = 'New'                                    THEN 'New'
      ELSE 'Other'
    END AS status_bucket
  FROM `bidbrain-analytics.client_cloudflare.salesforce_leads_live`
),
cut AS (SELECT MAX(day_idx) AS max_idx FROM tagged WHERE quarter = 'Q3')   -- how far into Q3 we have data
SELECT
  quarter, market, status_bucket,
  (SELECT max_idx FROM cut)                                    AS asof_day_idx,
  DATE_ADD(DATE '2026-07-01', INTERVAL (SELECT max_idx FROM cut) DAY) AS asof_date,
  COUNT(*)                                                     AS leads_full,   -- whole quarter
  COUNTIF(day_idx <= (SELECT max_idx FROM cut))                AS leads_qtd     -- first (max_idx+1) days
FROM tagged
WHERE quarter IS NOT NULL
  AND market <> 'OTHER'                                        -- 11 market chips only (matches the dash)
GROUP BY quarter, market, status_bucket
ORDER BY quarter, market, status_bucket;
