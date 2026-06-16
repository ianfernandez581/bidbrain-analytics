CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_leads` AS
-- By-market CS rollup. "Do Not Contact" is an IDC-only status (KGA/IDC's syndicated-but-
-- unactioned leads); count it as still-pending NEW_LEADS so ACCEPTED + REJECTED + NEW_LEADS
-- reconciles to TOTAL_LEADS (and matches cs_leads_by_programme's IDC "delivered" definition).
SELECT MARKET, COUNT(*) AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  COUNTIF(LEAD_STATUS IN ("Unresponsive","Do Not Contact","New")) AS NEW_LEADS,
  MAX(DAY) AS LAST_LEAD_DAY
FROM `bidbrain-analytics.client_mongodb.stg_salesforce` GROUP BY MARKET
