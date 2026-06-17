-- stg_linkedin: Cloudflare's LinkedIn slice of the shared raw mirror.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINKEDIN_CF, now reading
-- the BigQuery mirror raw_snowflake.linkedin_ads_apac (landed by ingest/snowflake_data_pull)
-- instead of APAC_ALL_PLATFORM.PUBLIC."LinkedIn Ads - APAC" in Snowflake.
-- SELECT * keeps every column the downstream paid-media + creative views read.
CREATE OR REPLACE VIEW `client_cloudflare.stg_linkedin` AS
SELECT *
FROM `bidbrain-analytics.raw_snowflake.linkedin_ads_apac`
WHERE ACCOUNT_NAME = 'Cloudflare APAC';
