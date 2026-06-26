-- 09_fatigue: per-ad week-over-week frequency and CTR, to flag creative fatigue.
-- Fatigue = frequency rising AND CTR falling week-over-week. A per-ad row is flagged when both
-- conditions hold. Sorted by fatigue risk (biggest freq rise with biggest CTR drop first).
-- Only ads with >=2 weeks of data + a meaningful impression base are considered (small-sample
-- CPLs masquerading as insight is the trap the May report flagged).
CREATE OR REPLACE VIEW `bidbrain-analytics.client_geocon.fatigue` AS
WITH weekly AS (
  SELECT
    campaign_name,
    adset_name,
    ad_name,
    DATE_TRUNC(date, WEEK(MONDAY)) AS week_start,
    SUM(impressions) AS impressions,
    SUM(reach)       AS reach,
    SUM(link_clicks) AS link_clicks,
    SUM(impressions) / NULLIF(SUM(reach), 0)       AS frequency,
    SUM(link_clicks) / NULLIF(SUM(impressions), 0) AS ctr
  FROM `bidbrain-analytics.client_geocon.geocon_daily`
  GROUP BY campaign_name, adset_name, ad_name, week_start
),
qualified AS (
  -- small-sample guard: drop weeks with <1000 impressions (noise, not signal)
  SELECT * FROM weekly WHERE impressions >= 1000
),
with_prev AS (
  SELECT
    campaign_name, adset_name, ad_name, week_start, impressions, frequency, ctr,
    LAG(frequency) OVER (PARTITION BY campaign_name, adset_name, ad_name ORDER BY week_start) AS prev_freq,
    LAG(ctr)        OVER (PARTITION BY campaign_name, adset_name, ad_name ORDER BY week_start) AS prev_ctr
  FROM qualified
)
SELECT
  campaign_name,
  adset_name,
  ad_name,
  week_start,
  impressions,
  frequency,
  ctr,
  prev_freq,
  prev_ctr,
  frequency - prev_freq AS freq_wow,
  ctr - prev_ctr        AS ctr_wow,
  CASE WHEN prev_freq IS NOT NULL
        AND frequency > prev_freq
        AND ctr < prev_ctr
       THEN 'FATIGUED'
       WHEN prev_freq IS NOT NULL THEN 'OK'
       ELSE 'NEW' END AS flag
FROM with_prev
WHERE prev_freq IS NOT NULL   -- only ads with >=2 weeks
ORDER BY freq_wow DESC, ctr_wow ASC