-- benchmarks_channel: media-plan benchmarks keyed by channel.
-- Pass-through of src_benchmarks_channel (from V_BENCHMARKS_CHANNEL).
-- CHANNEL values must match the dashboard: TTD, LinkedIn, Reddit, LINE.
CREATE OR REPLACE VIEW `client_cloudflare.benchmarks_channel` AS
SELECT
    CHANNEL,
    CTR,
    CPM,
    CPC
FROM `client_cloudflare.src_benchmarks_channel`;
