-- TLM — Trade Desk delivery by creative_name + ad_format. Top by imps.
-- Video funnel columns (video_starts/25/50/75/completes) are included in the
-- stg view but EDA shows they are all 0 for TLM — no video creative. The
-- dashboard skips the video funnel chart when these are empty.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_tlm.ttd_creative` AS
SELECT
  creative_name,
  ad_format,
  SUM(imps)      AS imps,
  SUM(clicks)    AS clicks,
  SUM(spend_aud) AS spend_aud,
  SUM(video_starts)     AS video_starts,
  SUM(video_completes)  AS video_completes
FROM `bidbrain-analytics.client_tlm.stg_ttd`
GROUP BY creative_name, ad_format
ORDER BY imps DESC;