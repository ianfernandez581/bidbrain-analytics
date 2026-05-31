-- benchmarks_market: media-plan benchmarks keyed by market.
-- Pass-through of src_benchmarks_market (from V_BENCHMARKS_MARKET).
-- MARKET values must match the dashboard: ANZ, ASEAN, SAARC, RIG, KR, JP, GCR.
CREATE OR REPLACE VIEW `client_cloudflare.benchmarks_market` AS
SELECT
    MARKET,
    CTR,
    CPM,
    CPC
FROM `client_cloudflare.src_benchmarks_market`;
