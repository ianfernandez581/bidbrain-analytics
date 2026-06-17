-- stg_line: LINE JP delivery (Japan-only paid channel).
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_LINE_CF, now a pass-through
-- of the committed static seed client_cloudflare.seed_line_cf (loaded by seed_static.py
-- from data/line_cf.csv). LINE is a manual upload, not in the raw_snowflake mirror.
-- The messy source header "Video (100% watched)" was aliased to VIDEO_100_WATCHED at pull.
CREATE OR REPLACE VIEW `client_cloudflare.stg_line` AS
SELECT
    DAY,
    AD_NAME,
    IMPRESSIONS,
    CLICKS,
    COST,
    VIDEO_STARTS,
    VIDEO_100_WATCHED
FROM `client_cloudflare.seed_line_cf`;
