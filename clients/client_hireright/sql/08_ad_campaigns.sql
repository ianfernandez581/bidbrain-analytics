-- HireRight - ad delivery by campaign (whole flight): the Campaign filter's option
-- list + per-campaign totals. One row per platform x campaign, delivering campaigns
-- only (zero-impression / zero-spend shells dropped). Ordered by spend so the
-- dropdown surfaces the campaigns that matter at the top. The dashboard sums the
-- selected campaigns client-side to rescale every ad-delivery figure.
-- (Delivering filter is an outer WHERE, not HAVING, so the SUM aliases below don't
-- get re-aggregated - BigQuery resolves HAVING against SELECT aliases.)
--
-- `campaign` is the NORMALISED name (brief-number prefix stripped in the stg_* views),
-- so a campaign that gets prefixed mid-flight stays ONE row here instead of splitting
-- into two. `brief` is carried as MAX() - it is NULL until the prefix appears and then
-- constant, so MAX picks up the number without splitting the group.
--
-- Outcomes are kept apart, never summed: `leads` (LinkedIn lead-gen forms) vs
-- `attr_conv` (DV360 + TTD post-click/post-view attributed). See 04_stg_ad_delivery.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_hireright.ad_campaigns` AS
WITH agg AS (
  SELECT
    platform,
    campaign,
    MAX(brief)       AS brief,
    SUM(imps)        AS imps,
    SUM(clicks)      AS clicks,
    SUM(spend_usd)   AS spend_usd,
    SUM(engagements) AS engagements,
    SUM(leads)       AS leads,
    SUM(attr_conv)   AS attr_conv,
    MIN(metric_date) AS start_date,
    MAX(metric_date) AS end_date
  FROM `bidbrain-analytics.client_hireright.stg_ad_delivery`
  GROUP BY platform, campaign
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_usd > 0
ORDER BY spend_usd DESC;
