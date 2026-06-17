-- benchmarks_channel: media-plan benchmarks keyed by channel (constants).
-- Port of CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_BENCHMARKS_CHANNEL, which is a
-- hardcoded literal view -- so it's reproduced verbatim here (no data pull needed).
-- CHANNEL values must match the dashboard: TTD, LinkedIn, Reddit, LINE.
CREATE OR REPLACE VIEW `client_cloudflare.benchmarks_channel` AS
SELECT 'TTD'      AS CHANNEL, 0.00112 AS CTR, 10.07 AS CPM,  9.02 AS CPC
UNION ALL SELECT 'LinkedIn', 0.00488, 49.48, 10.13
UNION ALL SELECT 'Reddit',   0.00200,  5.00,  2.00
UNION ALL SELECT 'LINE',     0.00100,  0.70,  0.70;
