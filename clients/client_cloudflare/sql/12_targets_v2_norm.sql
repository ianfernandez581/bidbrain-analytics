-- targets_v2_norm: weekly pacing targets normalised to the MARKET_REGION grain.
-- BigQuery port of CLOUDFLARE_SANDBOX.CS_REPORTING.V_TARGETS_V2_NORM, over the static
-- seed client_cloudflare.seed_real_targets (from data/real_targets.csv). The DATE column
-- holds week-start Mondays (matches DATE_TRUNC(DAY, WEEK(MONDAY)) in pacing_model).
CREATE OR REPLACE VIEW `client_cloudflare.targets_v2_norm` AS
SELECT
    `DATE` AS WEEK_START,
    CASE
        WHEN REGION = 'JAPAN' THEN 'JP'
        WHEN REGION = 'KOREA' THEN 'KR'
        ELSE REGION        -- ANZ, ASEAN, SAARC, GCR, RIG pass through unchanged
    END AS MARKET_REGION,
    TIER,
    SUM(TARGET) AS WEEKLY_TIER_TARGET
FROM `client_cloudflare.seed_real_targets`
GROUP BY 1, 2, 3;
