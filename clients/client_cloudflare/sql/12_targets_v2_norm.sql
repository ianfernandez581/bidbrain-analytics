-- targets_v2_norm: weekly pacing targets normalised to the MARKET_REGION grain.
-- Over the committed seed client_cloudflare.seed_real_targets (from the version-controlled
-- targets/real_targets.csv -- the per-client "targets live in BQ from a committed CSV" standard).
-- The DATE column holds week-start Mondays (matches DATE_TRUNC(DAY, WEEK(MONDAY)) in pacing_model).
-- 2026-06-25: maps the seed's (REGION, COUNTRY) to the 11 media-plan market codes so the targets
-- join the lead REGION_GRP codes 1:1 (sql/10): ANZ->AU/NZ, ASEAN->SIM/ROA, GCR->GCR-CN/TW/HK.
CREATE OR REPLACE VIEW `client_cloudflare.targets_v2_norm` AS
SELECT
    `DATE` AS WEEK_START,
    CASE
        WHEN REGION = 'ANZ'   AND COUNTRY = 'Australia'      THEN 'AU'
        WHEN REGION = 'ANZ'   AND COUNTRY = 'New Zealand'    THEN 'NZ'
        WHEN REGION = 'ASEAN' AND COUNTRY LIKE 'SIM%'        THEN 'SIM'
        WHEN REGION = 'ASEAN' AND COUNTRY LIKE 'RoA%'        THEN 'ROA'
        WHEN REGION = 'SAARC'                                THEN 'SAARC'
        WHEN REGION = 'GCR'   AND COUNTRY = 'Mainland China' THEN 'GCR-CN'
        WHEN REGION = 'GCR'   AND COUNTRY = 'Taiwan'         THEN 'GCR-TW'
        WHEN REGION = 'GCR'   AND COUNTRY = 'Hong Kong'      THEN 'GCR-HK'
        WHEN REGION = 'JAPAN'                                THEN 'JP'
        WHEN REGION = 'KOREA'                                THEN 'KR'
        WHEN REGION = 'RIG'                                  THEN 'RIG'
    END AS MARKET_REGION,
    TIER,
    SUM(TARGET) AS WEEKLY_TIER_TARGET
FROM `client_cloudflare.seed_real_targets`
GROUP BY 1, 2, 3;
