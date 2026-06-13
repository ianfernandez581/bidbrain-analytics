-- paid_media_model: per-channel/market/day paid delivery for the dashboard.
-- Thin pass-through of src_paid_media (landed by the job from Snowflake's
-- CLOUDFLARE_SANDBOX.PAID_MEDIA_REPORTING.V_PAID_ADS_FINAL_MODEL).
-- Columns listed explicitly to lock the JSON contract the dashboard depends on.
CREATE OR REPLACE VIEW `client_cloudflare.paid_media_model` AS
SELECT
    CHANNEL,
    DATE,
    WEEK_START,
    MARKET,
    IMPS,
    CLICKS,
    SPEND_USD,
    LEADS,
    FORM_OPENS,
    LINK_CLICKS,
    ACTION_CLICKS,
    VIDEO_STARTS,
    VIDEO_COMPLETIONS,
    SPEND_JPY,
    FX_USD_JPY
FROM `client_cloudflare.src_paid_media`;
