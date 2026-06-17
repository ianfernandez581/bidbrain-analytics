-- benchmarks_market: media-plan benchmarks keyed by market (constants).
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_BENCHMARKS_MARKET (hardcoded literal view).
-- MARKET values must match the dashboard: ANZ, ASEAN, SAARC, RIG, KR, JP, GCR.
CREATE OR REPLACE VIEW `client_cloudflare.benchmarks_market` AS
SELECT 'ANZ'   AS MARKET, 0.00179 AS CTR, 29.06 AS CPM, 16.27 AS CPC
UNION ALL SELECT 'ASEAN', 0.00200, 12.00,  4.00
UNION ALL SELECT 'SAARC', 0.00199,  8.59,  4.32
UNION ALL SELECT 'RIG',   0.00199,  8.59,  4.32
UNION ALL SELECT 'KR',    0.00342, 10.02,  2.93
UNION ALL SELECT 'JP',    0.00339,  9.90,  2.92
UNION ALL SELECT 'GCR',   0.00214, 17.39, 11.42;
