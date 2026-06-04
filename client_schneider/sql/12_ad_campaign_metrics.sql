-- Schneider Electric — campaign-grained FUNNEL metrics across the three platforms, for the
-- Delivery & Funnel tab (Impressions → Clicks/CTR/CPC → Video/VCR → Conversions/Leads). The
-- unified stg_ad_delivery only carries imps/clicks/spend, so the richer metrics (video, leads,
-- conversions, engagements, viewable) are folded here per platform × campaign (0 where a metric
-- doesn't apply to that platform). The dashboard sums these over the selected campaigns.
--   VCR = video_completions / video_starts  (LinkedIn)
--   Conversions = DV360 CONVERSIONS_TOTAL + TradeDesk click+view conversions
--   Leads       = LinkedIn LEADS + LEAD_FORM_OPENS
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.ad_campaign_metrics` AS
WITH agg AS (
  SELECT 'dv360' AS platform, campaign_name AS campaign,
    SUM(imps) AS imps, SUM(clicks) AS clicks, SUM(spend_aud) AS spend_aud,
    SUM(conversions) AS conversions,
    CAST(0 AS INT64) AS video_starts, CAST(0 AS INT64) AS video_completions, CAST(0 AS INT64) AS video_views,
    CAST(0 AS INT64) AS leads, CAST(0 AS INT64) AS lead_form_opens,
    SUM(engagements) AS engagements, SUM(viewable_imps) AS viewable_imps
  FROM `bidbrain-analytics.client_schneider.stg_dv360` GROUP BY campaign_name
  UNION ALL
  SELECT 'tradedesk', campaign_name,
    SUM(imps), SUM(clicks), SUM(spend_aud),
    SUM(conversions),
    0, 0, 0,
    0, 0,
    0, 0
  FROM `bidbrain-analytics.client_schneider.stg_tradedesk` GROUP BY campaign_name
  UNION ALL
  SELECT 'linkedin', campaign_name,
    SUM(imps), SUM(clicks), SUM(cost_aud),
    0,
    SUM(video_starts), SUM(video_completions), SUM(video_views),
    SUM(leads), SUM(lead_form_opens),
    SUM(engagements), 0
  FROM `bidbrain-analytics.client_schneider.stg_linkedin` GROUP BY campaign_name
)
SELECT * FROM agg
WHERE imps > 0 OR clicks > 0 OR spend_aud > 0
ORDER BY spend_aud DESC;
