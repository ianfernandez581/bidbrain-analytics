-- paid_creatives_model: per-channel/market/creative paid delivery, aggregated over
-- the whole window. Powers the "Top & bottom performing creatives" tables on the
-- Paid Media tab. Thin pass-through of src_paid_creatives, which the job lands from
-- a creative-grain query against Snowflake's per-channel staging views
-- (CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_STG_*). That query mirrors the exact
-- channel filters + market-derivation of V_PAID_ADS_FINAL_MODEL, but keeps the
-- creative dimension the final model collapses away (see PAID_CREATIVES_SQL in
-- client_cloudflare/job/main.py).
-- Columns listed explicitly to lock the JSON contract the dashboard depends on.
CREATE OR REPLACE VIEW `client_cloudflare.paid_creatives_model` AS
SELECT
    CHANNEL,
    MARKET,
    CREATIVE,
    IMPS,
    CLICKS,
    SPEND_USD,
    LEADS
FROM `client_cloudflare.src_paid_creatives`;
