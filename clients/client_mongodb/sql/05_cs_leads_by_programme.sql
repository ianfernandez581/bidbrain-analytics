CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_leads_by_programme` AS
-- The KGA (IDC) campaign (701RG00001NKKwQYAX) is the ONLY NULL-PROGRAMME_LABEL group
-- here (the 3 DNB programmes are labelled in stg_salesforce). Per the client's
-- definition an IDC lead is "delivered" only when its status is Unresponsive /
-- Do Not Contact / New — so IDC's TOTAL_LEADS (= the dash's Total/Delivered number)
-- and its still-pending NEW_LEADS count exactly those three statuses. The DNB
-- programmes keep the full COUNT(*) Accepted/Rejected/New(=Unresponsive+New) lifecycle.
SELECT PROGRAMME_LABEL, MARKET,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNT(*)
  END AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  CASE WHEN PROGRAMME_LABEL IS NULL
       THEN COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New"))
       ELSE COUNTIF(LEAD_STATUS IN ("Unresponsive","New"))
  END AS NEW_LEADS,
  MAX(DAY) AS LAST_LEAD_DAY
FROM `bidbrain-analytics.client_mongodb.stg_salesforce` GROUP BY PROGRAMME_LABEL, MARKET
