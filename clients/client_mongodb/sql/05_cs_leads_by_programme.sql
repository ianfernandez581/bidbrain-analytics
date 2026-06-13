CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.cs_leads_by_programme` AS
SELECT PROGRAMME_LABEL, MARKET, COUNT(*) AS TOTAL_LEADS,
  COUNTIF(LEAD_STATUS="Accepted") AS ACCEPTED,
  COUNTIF(LEAD_STATUS="Rejected") AS REJECTED,
  COUNTIF(LEAD_STATUS IN ("Unresponsive","New")) AS NEW_LEADS,
  MAX(DAY) AS LAST_LEAD_DAY
FROM `bidbrain-analytics.client_mongodb.stg_salesforce` GROUP BY PROGRAMME_LABEL, MARKET
