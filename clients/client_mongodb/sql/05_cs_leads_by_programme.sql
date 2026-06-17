CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_leads_by_programme` AS
-- The KGA (IDC) campaign (701RG00001NKKwQYAX) is the ONLY NULL-PROGRAMME_LABEL group
-- here (the 3 DNB programmes are labelled in stg_salesforce). Two "delivered" definitions
-- for TOTAL_LEADS (= the dash's Total/Delivered number):
--   * KGA(IDC): delivered only when Unresponsive / Do Not Contact / New — so its
--     TOTAL_LEADS and still-pending NEW_LEADS count exactly those three statuses.
--   * DNB (the 3 programmes): TOTAL_LEADS counts New + Unresponsive + Accepted ONLY (the
--     client's delivered-lead definition) — this EXCLUDES 'Unqualified' and 'Rejected',
--     so it is NOT COUNT(*). (COUNT(*) over-counted by the 3 'Unqualified' Technical-DMs
--     leads: 402 vs the correct 399.) ACCEPTED/REJECTED/NEW keep the full lifecycle
--     breakdown (NEW = Unresponsive + New) and reconcile to TOTAL_LEADS.
SELECT PROGRAMME_LABEL, MARKET,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNTIF(LEAD_STATUS IN ("New","Unresponsive","Accepted"))
  END AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNTIF(LEAD_STATUS IN ("Unresponsive","New"))
  END AS NEW_LEADS,
  MAX(DAY) AS LAST_LEAD_DAY
FROM `bidbrain-analytics.client_mongodb.stg_salesforce` GROUP BY PROGRAMME_LABEL, MARKET
