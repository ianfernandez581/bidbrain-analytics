CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_daily` AS
-- Day-grain twin of cs_leads_by_programme (view 05): the SAME delivered-lead definitions,
-- one row per PROGRAMME_LABEL x MARKET x DAY. Powers the Content Syndication "Weekly pacing"
-- chart, which buckets these days into Monday weeks client-side.
--
-- Every Salesforce lead in stg_salesforce carries a populated DAY (verified: 0 NULLs), so
-- these are TRUE actuals. The chart used to have none of this - it spread the whole-flight
-- lead total evenly across the elapsed window, which invented identical leads in weeks that
-- had zero delivery (KGA/IDC stopped 2026-07-02 but the bars ran to the plan end 07-31) and
-- buried the real mid-May spike.
--
-- The two "delivered" definitions must stay in step with view 05 or the weekly bars stop
-- summing to the headline Total/Delivered number:
--   * KGA(IDC) - the ONLY NULL-PROGRAMME_LABEL group: delivered = Unresponsive / Do Not
--     Contact / New (client definition, no Accepted/Rejected lifecycle).
--   * DNB - the 3 labelled programmes: delivered = New + Unresponsive + Accepted (EXCLUDES
--     Unqualified / Rejected, so it is NOT COUNT(*)).
-- ACCEPTED / REJECTED / NEW_LEADS keep the full lifecycle breakdown at day grain too, so a
-- future date-scoped CS view can read this one view instead of needing another.
SELECT PROGRAMME_LABEL, MARKET, DAY,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNTIF(LEAD_STATUS IN ("New","Unresponsive","Accepted"))
  END AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNTIF(LEAD_STATUS IN ("Unresponsive","New"))
  END AS NEW_LEADS
FROM `bidbrain-analytics.client_mongodb.stg_salesforce`
GROUP BY PROGRAMME_LABEL, MARKET, DAY
ORDER BY DAY, PROGRAMME_LABEL, MARKET
