-- PropTrack (Transmission) — LinkedIn delivery by campaign group / objective (whole flight).
-- CAMPAIGN_GROUP_NAME is the initiative grouping; the dashboard maps the 4 raw groups to friendly
-- labels (COBA Event, General — Nov 2025, Banking ABM — Awareness, Banking ABM — Lead Gen).
-- Ordered by spend desc.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_proptrack.li_groups` AS
SELECT
  campaign_group,
  SUM(imps)            AS imps,
  SUM(clicks)          AS clicks,
  SUM(spend_aud)       AS spend_aud,
  SUM(engagements)     AS engagements,
  SUM(video_views)     AS video_views,
  SUM(lead_form_opens) AS lead_form_opens
FROM `bidbrain-analytics.client_proptrack.stg_linkedin`
GROUP BY campaign_group
ORDER BY spend_aud DESC;
