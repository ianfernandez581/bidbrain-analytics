-- Schneider Electric - PUBLISHER REPORT DELIVERY (Other Channels tab), added 2026-09-14.
--
-- Direct publisher buys that have NO API feed and never will: Capital Brief, Energy Magazine
-- (Project ENGY) and Westwick-Farrow (ECD Online / Sustainability Matters) for the Advancing Energy
-- Technology brief. The publishers email a PDF or a workbook each month; those figures are re-keyed
-- into data/publisher_reports.csv + data/publisher_report_meta.csv, loaded by load_seeds.py, and
-- read here. This is the SAME committed-CSV -> seed_* -> view -> job path the plan targets on this
-- tab already take (data/media_plan.csv -> seed_media_plan), which is why no new mechanism was
-- invented for it: a monthly reload is a CSV edit plus deploy_seeds_schneider.ps1.
--
-- WHY NOT SNOWFLAKE: our roles on the shared warehouse are READ-ONLY, so we cannot write a
-- hand-keyed publisher report there at all, and these numbers have no upstream system to be
-- sourced FROM - they exist first as a PDF in an inbox. A committed CSV is also the only form that
-- travels with the repo and can be diffed when a figure is questioned.
--
-- =====================================================================================
-- `unit` IS THE SAFETY MECHANISM, NOT A LABEL. Read this before adding a row.
-- =====================================================================================
-- These publishers report several things that all look like a big number in a spreadsheet cell and
-- are NOT the same measure. Article views are people reading a sponsored article; solus eDM sends
-- are emails despatched; neither is an impression, and summing any of them into an impression total
-- would overstate reach on a line the client is buying on reach. So the total is not defined as
-- "sum the quantity column" - it is defined as "sum the quantity column WHERE unit = 'impressions'",
-- and everything else is structurally excluded rather than excluded by whoever writes the next
-- consumer remembering to exclude it.
--   impressions   - the only unit that may enter an impression total.
--   sends         - solus eDM despatches. Carry clicks; never impressions.
--   article_views - sponsored-article reads, paced against booked_quantity, never against a plan
--                   impression target.
--   rate          - a publisher-reported rate (open rate, viewability). NEVER summed anywhere; the
--                   dashboard takes a delivery-weighted mean. `metric` names which rate it is.
-- Anything outside that vocabulary lands in unit = 'UNKNOWN', is excluded from EVERY total, and is
-- WARNed by the export job - the loud failure, not a silent absorption into impressions.
--
-- CLICKS sum across all three DELIVERY units (a solus click is a real click the publisher reports)
-- but never across rate rows. That asymmetry is deliberate and is why clicks are not gated on
-- counts_as_impressions.
--
-- GRAIN: campaign x publisher x period x placement. One row per line the publisher reports. Where a
-- publisher states an impression count once across two slots that shared a send (Westwick's paired
-- text panels and side bars), the second slot's quantity is left NULL rather than zeroed - NULL is
-- "not separately reported", 0 would be a claim that it delivered nothing.
--
-- NO SPEND, NO MARKET, NO DAY. These are monthly aggregates with no cost and no region split, so
-- they must never reach pm_delivery, the blended KPI band, or any spend/CPM figure - and a date
-- range that cuts mid-month cannot be honoured from a month bucket. The tab renders them whole-
-- flight, exactly as it already renders the plan lines.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.publisher_delivery` AS
WITH src AS (
  SELECT
    TRIM(internal_campaign_id)                                  AS campaign,
    LOWER(TRIM(publisher))                                      AS publisher,
    TRIM(period_label)                                          AS period_label,
    period_start,
    period_end,
    NULLIF(TRIM(COALESCE(placement_group, '')), '')             AS placement_group,
    NULLIF(TRIM(COALESCE(placement, '')), '')                   AS placement,
    LOWER(TRIM(COALESCE(unit, '')))                             AS unit_raw,
    NULLIF(TRIM(COALESCE(metric, '')), '')                      AS metric,
    quantity,
    clicks,
    booked_quantity,
    NULLIF(TRIM(COALESCE(note, '')), '')                        AS note
  FROM `bidbrain-analytics.client_schneider.seed_publisher_reports`
  -- A wholly blank line (trailing newline in a hand-edited CSV) is not a data point.
  WHERE COALESCE(TRIM(internal_campaign_id), '') <> ''
    AND COALESCE(TRIM(publisher), '') <> ''
)
SELECT
  campaign,
  publisher,
  period_label,
  period_start,
  period_end,
  placement_group,
  placement,
  -- Closed vocabulary. An unrecognised unit is named UNKNOWN and counted nowhere.
  CASE unit_raw
    WHEN 'impressions'   THEN 'impressions'
    WHEN 'sends'         THEN 'sends'
    WHEN 'article_views' THEN 'article_views'
    WHEN 'rate'          THEN 'rate'
    ELSE 'UNKNOWN'
  END                                                            AS unit,
  metric,
  quantity,
  -- The single enforcement point every consumer reads instead of re-testing the unit string.
  (unit_raw = 'impressions')                                     AS counts_as_impressions,
  (unit_raw = 'rate')                                            AS is_rate,
  -- Pre-split measures, so a consumer physically cannot add a send to an impression by writing
  -- SUM(quantity). Each is NULL - never 0 - outside its own unit: 0 would assert a measured zero.
  IF(unit_raw = 'impressions',   quantity, NULL)                 AS impressions,
  IF(unit_raw = 'sends',         quantity, NULL)                 AS sends,
  IF(unit_raw = 'article_views', quantity, NULL)                 AS article_views,
  IF(unit_raw = 'rate',          quantity, NULL)                 AS rate_value,
  -- Clicks are real on every delivery unit, and meaningless on a rate row.
  IF(unit_raw = 'rate', NULL, clicks)                            AS clicks,
  IF(unit_raw = 'rate', NULL, booked_quantity)                   AS booked_quantity,
  note
FROM src;
