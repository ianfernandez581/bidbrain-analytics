-- STT GDC — ad delivery by campaign × market × month, for the Overview
-- "Media spend by platform" donut so it honours the Country filter AND the date
-- picker at once (Platform + Campaign already applied client-side).
--
-- This is the market grain of `ad_campaign_monthly` (20) — same source, plus the
-- `market` column. UNLIKE `ad_campaign_market` (22) we KEEP `market IS NULL` rows:
-- LinkedIn carries no market (see 03c), so its spend lives only in NULL-market rows.
-- The dashboard includes those NULL rows ONLY when the Country filter is at "All"
-- (no country narrowing); selecting specific countries drops LinkedIn, since no
-- per-country LinkedIn spend exists to attribute.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_stt.ad_campaign_market_monthly` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    market,                                   -- NULL for LinkedIn (no market grain)
    FORMAT_DATE('%Y-%m', metric_date) AS month,
    SUM(imps)      AS imps,
    SUM(clicks)    AS clicks,
    SUM(spend_sgd) AS spend_sgd
  FROM `bidbrain-analytics.client_stt.stg_ad_delivery`
  GROUP BY platform, campaign, market, month
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_sgd > 0
ORDER BY month, platform, campaign, imps DESC;
