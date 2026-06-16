CREATE OR REPLACE VIEW `bidbrain-analytics.client_mongodb.stg_salesforce` AS
SELECT DAY, COUNTRY_NAME, CAMPAIGN_ID, LEAD_STATUS,
  CASE CAMPAIGN_ID
    WHEN "701RG00001DtQczYAF" THEN "DNB IDE Single Touch"
    WHEN "701RG00001HcDIVYA3" THEN "DNB IDE Technical DMs"
    WHEN "701RG00001GvvrDYAR" THEN "DNB IDE Business & Ops Leaders"
  END AS PROGRAMME_LABEL,
  -- Market bucket. Normalise COUNTRY_NAME (UPPER + TRIM) so case / spelling variants
  -- ("INDIA"/"india", "Republic of Korea") land in the right market instead of falling
  -- through to OTHER. Countries outside the 4 plan markets (e.g. China, Japan) stay OTHER,
  -- which the dashboard surfaces as its own region so every lead is counted.
  CASE
    WHEN UPPER(TRIM(COUNTRY_NAME)) IN ("AUSTRALIA","NEW ZEALAND") THEN "ANZ"
    WHEN UPPER(TRIM(COUNTRY_NAME)) = "INDIA" THEN "INDIA"
    WHEN UPPER(TRIM(COUNTRY_NAME)) IN ("SINGAPORE","MALAYSIA","INDONESIA","THAILAND","PHILIPPINES","VIETNAM","VIET NAM","MYANMAR") THEN "ASEAN"
    WHEN UPPER(TRIM(COUNTRY_NAME)) IN ("KOREA","SOUTH KOREA","KOREA, REPUBLIC OF","REPUBLIC OF KOREA","KR","HONG KONG","TAIWAN") THEN "KR-HK-TW"
    ELSE "OTHER"
  END AS MARKET
FROM (
  SELECT DAY, COUNTRY_NAME, CAMPAIGN_ID, LEAD_STATUS
  FROM `bidbrain-analytics.raw_snowflake.salesforce_cs_apac_all`
  WHERE CAMPAIGN_ID IN ("701RG00001DtQczYAF","701RG00001HcDIVYA3","701RG00001GvvrDYAR","701RG00001NKKwQYAX")
)
