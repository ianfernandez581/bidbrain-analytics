-- VMCH — staged GA4 website analytics, with a DTS→Windsor fallback.
--
-- Source grain: one row per day × session_source_medium × channel × campaign,
-- session columns on the row. VMCH is AU-only (no geo/market dimension).
-- Conversions = the GA4 key-events metric.
--
-- TWO SOURCES, PER-DATE PRECEDENCE (added 2026-06-18) — NO DOUBLE COUNTING:
--   * PRIMARY  = native GA4 Data Transfer (`raw_ga4.perf_ga4`, account VMCH Website - GA4).
--   * FALLBACK = Windsor GA4 connector (`raw_windsor.perf_ga4`, property 287370621).
-- The DTS transfer for this property is FAILING on a permission error (it froze at
-- 2026-06-01; other clients on a still-valid credential keep updating). Windsor is a
-- SEPARATE, healthy auth path. So we keep the DTS as the trusted source for every date it
-- has, and use Windsor ONLY for dates the DTS is missing (the gap, 2026-06-02 →). The
-- `pick` CTE enforces this per-date, so a date is never counted from both — and if the DTS
-- transfer is later re-authorised, its dates automatically resume precedence (Windsor falls
-- back to gap-only again). All numeric columns are CAST so the UNION types line up.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_vmch.stg_ga4` AS
WITH src AS (
  SELECT
    metric_date, session_default_channel_group, session_source_medium, session_campaign_name,
    CAST(sessions AS INT64) AS sessions, CAST(engaged_sessions AS INT64) AS engaged_sessions,
    CAST(total_users AS INT64) AS total_users, CAST(new_users AS INT64) AS new_users,
    CAST(screen_page_views AS INT64) AS screen_page_views,
    CAST(user_engagement_duration AS NUMERIC) AS user_engagement_duration,
    CAST(conversions AS NUMERIC) AS conversions,
    'dts' AS _src
  FROM `bidbrain-analytics.raw_ga4.perf_ga4`
  WHERE account_name = 'VMCH Website - GA4'
  UNION ALL
  SELECT
    metric_date, session_default_channel_group, session_source_medium, session_campaign_name,
    CAST(sessions AS INT64), CAST(engaged_sessions AS INT64),
    CAST(total_users AS INT64), CAST(new_users AS INT64),
    CAST(screen_page_views AS INT64),
    CAST(user_engagement_duration AS NUMERIC),
    CAST(conversions AS NUMERIC),
    'windsor' AS _src
  FROM `bidbrain-analytics.raw_windsor.perf_ga4`
  WHERE property_id = '287370621'
),
dts_dates AS (SELECT DISTINCT metric_date FROM src WHERE _src = 'dts'),
pick AS (
  SELECT * FROM src
  WHERE _src = 'dts'                                                -- DTS wins on any date it has
     OR metric_date NOT IN (SELECT metric_date FROM dts_dates)      -- Windsor fills only the gap
)
SELECT
  metric_date,
  COALESCE(NULLIF(session_default_channel_group, ''), '(not set)') AS channel_group,
  CASE
    WHEN session_default_channel_group IN ('Paid Search','Paid Social','Paid Other','Paid Video','Cross-network','Display') THEN 'Paid'
    WHEN session_default_channel_group LIKE 'Organic%'        THEN 'Organic'
    WHEN session_default_channel_group = 'Direct'             THEN 'Direct'
    WHEN session_default_channel_group IN ('Referral','Email') THEN 'Referral'
    ELSE 'Other'
  END AS channel_bucket,
  COALESCE(NULLIF(session_source_medium, ''), '(not set)')   AS source_medium,
  COALESCE(NULLIF(session_campaign_name, ''), '(not set)')   AS campaign,
  sessions,
  engaged_sessions,
  total_users,
  new_users,
  screen_page_views,
  user_engagement_duration,
  conversions
FROM pick
  -- EXCLUDE the `programmatic-display / *` source/medium. GA4 dumps it into the "Unassigned"
  -- channel and it LOOKS like ~19-38k display sessions, but it is NOT credible campaign traffic:
  --   * it predates any loaded Trade Desk spend (peaks Mar-2026, before the Apr-2026 flight);
  --   * 12k of its April sessions came from just 144 Trade Desk clicks (physically impossible 1:1);
  --   * its engagement is 5.7% / 2.5s / 1.48 pp vs the site's 40% / 47s / 2.05 pp — a bot/redirect
  --     /landing-pixel signature, and it drags the whole-site engagement rate from ~46% to ~30%.
  -- Surfacing it as a "display win" to a sceptical client is indefensible, so it is filtered here
  -- once — keeping EVERY downstream metric (sessions, channels, monthly/daily, YoY) clean and
  -- internally consistent. The campaign's real contribution is shown via reach, clicks and the
  -- Trade-Desk-ATTRIBUTED post-view/post-click conversions (stg_ttd), not last-click sessions.
WHERE LOWER(COALESCE(session_source_medium, '')) NOT LIKE 'programmatic-display%';
