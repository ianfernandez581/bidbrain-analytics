-- stg_reddit: Cloudflare's Reddit slice of the shared raw mirror.
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_REDDIT_CF, now reading
-- raw_snowflake.reddit_ads_apac_all instead of APAC_ALL_PLATFORM.PUBLIC."Reddit Ads - APAC_ALL".
CREATE OR REPLACE VIEW `client_cloudflare.stg_reddit` AS
SELECT *
FROM `bidbrain-analytics.raw_snowflake.reddit_ads_apac_all`
WHERE ACCOUNT_NAME = 'Transmission_Cloudflare';
