-- li_weekly_targets: LinkedIn 13-week Q2 lead plan (weekly + cumulative).
-- Pass-through of src_li_weekly (from V_LI_WEEKLY_TARGETS).
CREATE OR REPLACE VIEW `client_cloudflare.li_weekly_targets` AS
SELECT
    WEEK,
    PERIOD,
    WEEK_START,
    TARGET,
    CUM_TARGET
FROM `client_cloudflare.src_li_weekly`;
