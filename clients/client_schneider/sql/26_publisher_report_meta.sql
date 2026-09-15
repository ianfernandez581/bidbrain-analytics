-- Schneider Electric - PUBLISHER REPORT META + PLAN MATCH (Other Channels tab), added 2026-09-14.
--
-- One row per campaign x publisher: how the card is labelled, where the figures came from, whether
-- the buy is finished, and - the load-bearing part - whether it matches a line in the media plan.
--
-- WHY THE PLAN MATCH IS AN EXPLICIT COLUMN AND NOT A NAME COMPARISON: a publisher is matched to its
-- plan line by `plan_channel`, a value a human states in data/publisher_report_meta.csv, joined on
-- (internal_campaign_id, channel) against seed_media_plan. Fuzzy-matching "Capital Brief" against a
-- plan channel string would be one publisher rename away from silently unpacing a live buy, which
-- is the repo-wide "names are not stable keys" rule.
--
-- THREE STATES, AND TWO OF THEM MUST NEVER LOOK ALIKE ON SCREEN:
-- `plan_match` describes ONLY the plan join, and `has_delivery` is separate, because the two are
-- genuinely independent: a buy can be planned and not yet reporting (Innovation Aus is booked but not
-- live). Folding "no delivery" into the enum threw away whether the plan_channel had resolved, which
-- is the one thing the tab needs in order to pace the line when its first report lands.
--   matched             - plan_channel names a real line. Delivery paces against it.
--   no_plan_row         - plan_channel is BLANK. A deliberate statement that this buy was never in
--                         the media plan (Westwick-Farrow). The tab shows the actuals flagged
--                         "missing plan row" and invents no target.
--   PLAN_ROW_NOT_FOUND  - plan_channel is SET but matches no line: a typo, or a plan line that was
--                         renamed underneath it. This is a DEFECT. Rendered as its own flag and
--                         WARNed by the export job, because rendering it as "missing plan row"
--                         would make a broken join indistinguishable from a real business fact.
--
-- Deliberately carries NO delivered totals. The dashboard computes every rendered figure from
-- publisher_delivery rows under the current campaign selection; a second copy of those totals here
-- is how two panels on one tab start disagreeing. What this view adds is the things rows cannot
-- carry: labels, provenance, status and the plan join.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.publisher_report_meta` AS
WITH meta AS (
  SELECT
    seq,
    TRIM(internal_campaign_id)                          AS campaign,
    TRIM(publisher)                                     AS publisher,
    NULLIF(TRIM(COALESCE(publisher_label, '')), '')     AS publisher_label,
    NULLIF(TRIM(COALESCE(plan_channel, '')), '')        AS plan_channel,
    NULLIF(TRIM(COALESCE(report_source, '')), '')       AS report_source,
    NULLIF(TRIM(COALESCE(report_label, '')), '')        AS report_label,
    NULLIF(TRIM(COALESCE(report_job, '')), '')          AS report_job,
    LOWER(NULLIF(TRIM(COALESCE(delivery_status, '')), '')) AS delivery_status,
    booked_article_views,
    -- status_note is CLIENT-FACING and is rendered. internal_note is NOT: it is agency
     -- commentary (a publisher's figures to query, a plan line to add) that the export job
     -- prints and deliberately never puts in the payload, so it cannot reach a client screen.
    NULLIF(TRIM(COALESCE(status_note, '')), '')         AS status_note,
    NULLIF(TRIM(COALESCE(internal_note, '')), '')       AS internal_note
  FROM `bidbrain-analytics.client_schneider.seed_publisher_report_meta`
  WHERE COALESCE(TRIM(internal_campaign_id), '') <> ''
    AND COALESCE(TRIM(publisher), '') <> ''
),
-- Every (campaign, publisher) that actually has delivery rows, so a meta row with no data - and a
-- data block with no meta row - are both visible to the job rather than quietly dropped by a join.
present AS (
  SELECT campaign, publisher,
         COUNT(*)                                            AS n_rows,
         COUNTIF(unit = 'UNKNOWN')                           AS n_unknown_unit,
         MIN(period_start)                                   AS first_period_start,
         MAX(period_end)                                     AS last_period_end
  FROM `bidbrain-analytics.client_schneider.publisher_delivery`
  GROUP BY campaign, publisher
)
SELECT
  COALESCE(m.seq, 999)                                        AS seq,
  COALESCE(m.campaign,  p.campaign)                           AS campaign,
  COALESCE(m.publisher, p.publisher)                          AS publisher,
  -- A publisher with no meta row still gets a legible name rather than vanishing.
  COALESCE(m.publisher_label, m.publisher, p.publisher)       AS publisher_label,
  m.plan_channel,
  m.report_source,
  m.report_label,
  m.report_job,
  COALESCE(m.delivery_status, 'complete')                     AS delivery_status,
  m.booked_article_views,
  m.status_note,
  m.internal_note,
  COALESCE(p.n_rows, 0)                                       AS n_rows,
  COALESCE(p.n_unknown_unit, 0)                               AS n_unknown_unit,
  p.first_period_start,
  p.last_period_end,
  -- Delivery presence is its own flag, NOT an arm of plan_match - see the header note.
  (p.campaign IS NOT NULL)                                    AS has_delivery,
  CASE
    WHEN m.campaign IS NULL             THEN 'NO_META_ROW'
    WHEN m.plan_channel IS NULL         THEN 'no_plan_row'
    WHEN EXISTS (SELECT 1
                 FROM `bidbrain-analytics.client_schneider.seed_media_plan` mp
                 WHERE TRIM(mp.internal_campaign_id) = m.campaign
                   AND LOWER(TRIM(mp.channel))       = LOWER(m.plan_channel))
                                        THEN 'matched'
    ELSE 'PLAN_ROW_NOT_FOUND'
  END                                                         AS plan_match,
  -- A campaign id that is not on the dashboard renders nowhere at all. Surfaced so the job can say
  -- so by name: under-inclusion here is otherwise completely silent.
  EXISTS (SELECT 1
          FROM `bidbrain-analytics.client_schneider.seed_campaign_map` cm
          WHERE TRIM(cm.internal_campaign_id) = COALESCE(m.campaign, p.campaign))
                                                              AS campaign_known
FROM meta m
FULL OUTER JOIN present p
  ON m.campaign = p.campaign AND LOWER(m.publisher) = LOWER(p.publisher);
