-- Cloudflare — Content-Syndication QUARTER-OVER-QUARTER (Q3 vs Q2), ACTUALS ONLY.
-- Client asked (2026-07): compare the new quarter (Q3, Jul-Sep) to the prior (Q2, Apr-Jun) for CS leads
-- — total accepted + by market + by status — from the start of Q3. No Q3 targets loaded yet, so this is
-- actuals vs actuals (no target/pacing here; that stays on the Q2 pacing model until Q3 targets arrive).
--
-- Built on salesforce_leads_live (sql/10) so it uses the SAME accepted-lead + market logic as the rest
-- of the dashboard: REGION_GRP = the 11 media-plan market chips (OTHER excluded — not a chip, matches
-- the dash summing over the chips); accepted = LEAD_STATUS IN (Accepted, Replied, Unresponsive) per
-- definitions.json status_buckets. Calendar quarters (Q2 = Apr-Jun, Q3 = Jul-Sep 2026).
-- Grain: one row per (quarter, market, status_bucket); the job/dashboard roll it up to
-- total / by-market / by-status and compute the Q3-vs-Q2 % change.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_cloudflare.cs_qoq` AS
WITH base AS (
  SELECT
    CASE
      WHEN DAY BETWEEN DATE '2026-04-01' AND DATE '2026-06-30' THEN 'Q2'
      WHEN DAY BETWEEN DATE '2026-07-01' AND DATE '2026-09-30' THEN 'Q3'
    END AS quarter,
    REGION_GRP AS market,
    CASE
      WHEN LEAD_STATUS IN ('Accepted', 'Replied', 'Unresponsive') THEN 'Accepted'
      WHEN LEAD_STATUS = 'Rejected'                               THEN 'Rejected'
      WHEN LEAD_STATUS = 'New'                                    THEN 'New'
      ELSE 'Other'
    END AS status_bucket
  FROM `bidbrain-analytics.client_cloudflare.salesforce_leads_live`
)
SELECT quarter, market, status_bucket, COUNT(*) AS leads
FROM base
WHERE quarter IS NOT NULL
  AND market <> 'OTHER'                       -- 11 market chips only (OTHER excluded, matches the dash)
GROUP BY quarter, market, status_bucket
ORDER BY quarter, market, status_bucket;
