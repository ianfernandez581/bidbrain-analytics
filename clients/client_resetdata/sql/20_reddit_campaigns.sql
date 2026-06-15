-- ResetData — Reddit delivery by campaign (whole flight): the community-awareness deep-dive
-- table on the Paid Media tab. One row per campaign with its objective + traffic signal.
-- spend_aud is AUD; conversions = sign-up + lead clicks (sparse, B2B); page_visits = page-visit
-- clicks + views (Reddit's traffic-driving signal). Delivering rows only via an outer WHERE
-- (see 13 for the aggregation-of-aggregation note). Ordered by spend so the heaviest flight leads.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_resetdata.reddit_campaigns` AS
WITH agg AS (
  SELECT
    campaign,
    ANY_VALUE(objective) AS objective,
    SUM(imps)            AS imps,
    SUM(clicks)          AS clicks,
    SUM(spend_aud)       AS spend_aud,
    SUM(conversions)     AS conversions,
    SUM(page_visits)     AS page_visits,
    MIN(metric_date)     AS start_date,
    MAX(metric_date)     AS end_date
  FROM `bidbrain-analytics.client_resetdata.stg_reddit`
  GROUP BY campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
