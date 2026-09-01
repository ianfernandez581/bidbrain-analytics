-- benchmarks_channel: media-plan benchmarks keyed by channel (constants).
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL, which is a
-- hardcoded literal view -- so it's reproduced verbatim here (no data pull needed).
-- CHANNEL values must match the dashboard: TTD, LinkedIn, Reddit, LINE, GoogleAds.
-- GoogleAds is NOT in Cloudflare's view (the channel joined in Q3, after the media plan);
-- its figures are the benchmark POINTS from the client-shared Q3 benchmark workbook
-- (CF_Q3_July_Channel_Benchmarks_v3.xlsx, Summary sheet): CTR = YouTube in-stream 0.12%
-- (band 0.07-0.17%), CPM = YouTube Japan USD 4.00 (band 2.70-10.00). That set commits NO
-- CPC benchmark, so CPC stays NULL - the dashboard renders "-" for it, never "vs $0.00".
CREATE OR REPLACE VIEW `client_cloudflare.benchmarks_channel` AS
SELECT 'TTD'      AS CHANNEL, 0.00112 AS CTR, 10.07 AS CPM,  9.02 AS CPC
UNION ALL SELECT 'LinkedIn',  0.00488, 49.48, 10.13
UNION ALL SELECT 'Reddit',    0.00200,  5.00,  2.00
UNION ALL SELECT 'LINE',      0.00100,  0.70,  0.70
UNION ALL SELECT 'GoogleAds', 0.00120,  4.00,  CAST(NULL AS FLOAT64);
