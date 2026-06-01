-- pacing_model: Content Syndication lead pacing for the dashboard.
-- Thin pass-through of src_pacing (landed by the job from Snowflake's
-- CLOUDFLARE_SANDBOX.CS_REPORTING.V_PACING_FINAL_MODEL).
-- SELECT * on purpose: the dashboard reads V_PACING_FINAL_MODEL columns by name
-- (LEAD_STATUS, MARKET_REGION, ALLOCATED_TARGET, DAY, LEAD_ID_SF, SERVICE,
--  COUNTRY_NAME, JOB_FUNCTION, JOB_LEVEL, ASSET_1, CUMULATIVE_ACTUAL, ...).
CREATE OR REPLACE VIEW `client_cloudflare.pacing_model` AS
SELECT *
FROM `client_cloudflare.src_pacing`;
