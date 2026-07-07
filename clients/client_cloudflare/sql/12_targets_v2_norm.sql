-- targets_v2_norm: weekly pacing targets normalised to the MARKET_REGION grain.
-- Over the committed seed client_cloudflare.seed_real_targets (from the version-controlled
-- targets/real_targets.csv -- the per-client "targets live in BQ from a committed CSV" standard).
-- The DATE column holds week-start Mondays (matches DATE_TRUNC(DAY, WEEK(MONDAY)) in pacing_model).
-- 2026-07-07: rolled the seed's (REGION, COUNTRY) targets back UP to the COARSE 7 market codes so
-- they join the lead REGION_GRP codes 1:1 (sql/10). The seed's REGION column already IS the coarse
-- grain (ANZ / ASEAN / SAARC / GCR / JAPAN / KOREA / RIG), so we just normalise JAPAN->JP, KOREA->KR
-- and SUM the per-country target rows into the 7 buckets (AU+NZ -> ANZ, SIM+RoA -> ASEAN, the three
-- GCR countries -> GCR). Grand total is unchanged (currently 3216).
CREATE OR REPLACE VIEW `client_cloudflare.targets_v2_norm` AS
SELECT
    `DATE` AS WEEK_START,
    CASE
        WHEN REGION = 'ANZ'   THEN 'ANZ'
        WHEN REGION = 'ASEAN' THEN 'ASEAN'
        WHEN REGION = 'SAARC' THEN 'SAARC'
        WHEN REGION = 'GCR'   THEN 'GCR'
        WHEN REGION = 'JAPAN' THEN 'JP'
        WHEN REGION = 'KOREA' THEN 'KR'
        WHEN REGION = 'RIG'   THEN 'RIG'
    END AS MARKET_REGION,   -- unknown REGION -> NULL (dropped), matching the old mapping's no-ELSE behaviour
    TIER,
    SUM(TARGET) AS WEEKLY_TIER_TARGET
FROM `client_cloudflare.seed_real_targets`
GROUP BY 1, 2, 3;
