CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_salesforce` AS
SELECT DAY, COUNTRY_NAME, CAMPAIGN_ID, LEAD_STATUS,
  CASE CAMPAIGN_ID
    WHEN "701RG00001DtQczYAF" THEN "DNB IDE Single Touch"
    WHEN "701RG00001HcDIVYA3" THEN "DNB IDE Technical DMs"
    WHEN "701RG00001GvvrDYAR" THEN "DNB IDE Business & Ops Leaders"
  END AS PROGRAMME_LABEL,
  CASE
    WHEN COUNTRY_NAME IN ("Australia","New Zealand") THEN "ANZ"
    WHEN COUNTRY_NAME IN ("India") THEN "INDIA"
    WHEN COUNTRY_NAME IN ("Singapore","Malaysia","Indonesia","Thailand","Philippines","Vietnam","Viet Nam","Myanmar") THEN "ASEAN"
    WHEN COUNTRY_NAME IN ("Korea","South Korea","Korea, Republic of","KR","Hong Kong","Taiwan") THEN "KR-HK-TW"
    ELSE "OTHER"
  END AS MARKET
FROM (
  -- Was client_mongodb.src_salesforce (landed by the export job's SF_SQL).
  -- Now reads the shared raw mirror (snowflake_data_pull) with the old SF_SQL
  -- campaign filter + the LEAD_STATUS != 'New' business rule applied here.
  SELECT DAY, COUNTRY_NAME, CAMPAIGN_ID, LEAD_STATUS
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
  WHERE CAMPAIGN_ID IN ("701RG00001DtQczYAF","701RG00001HcDIVYA3","701RG00001GvvrDYAR","701RG00001NKKwQYAX")
    AND LEAD_STATUS != "New"
)
