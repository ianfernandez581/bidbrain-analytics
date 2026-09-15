-- Schneider Electric - PUBLISHER REPORT DELIVERY (Other Channels tab). r2, 2026-09-15.
--
-- Direct publisher buys that have NO API feed and never will: Capital Brief, Energy Magazine
-- (Project ENGY) and the two Westwick-Farrow mastheads - ECD Online and Sustainability Matters -
-- for the Advancing Energy Technology brief. The publishers email a PDF or a workbook each month;
-- those figures are re-keyed into data/aet_publisher_reports_normalized.csv, loaded by
-- load_seeds.py, and read here.
--
-- r2 REPLACED the earlier hand-rolled narrow CSV with the account team's own normalised export
-- (one row per publisher x product x placement x month, wide measure columns). Its shape is kept
-- VERBATIM so a re-export drops straight in; this view does the mapping. The Snowflake sibling
-- data/load_publisher_reports_snowflake.sql holds the same rows for a warehouse route we do NOT
-- take - our roles on the shared warehouse are read-only, so we could not run it even if we wanted
-- the dependency, and these figures have no upstream system to be sourced FROM: they exist first
-- as an email attachment.
--
-- =====================================================================================
-- `product_type` IS THE SAFETY MECHANISM, NOT A LABEL. Read this before adding a row.
-- =====================================================================================
-- These publishers report several things that all look like a big number in a spreadsheet cell and
-- are NOT the same measure. Sponsored-article views are people reading an article; solus eDM sends
-- are emails despatched; neither is an impression, and summing any of them into an impression total
-- would overstate reach on a line the client is buying on reach. So the impression total is not
-- "sum the impressions column" - it is "sum WHERE unit = 'impressions'", and `unit` is derived from
-- a CLOSED list of product types:
--   content_newsletter / content_web / adv_newsletter / adv_display -> impressions
--   solus_edm                                                        -> sends
--   sponsored_article                                                -> article_views
-- Anything else lands in unit = 'UNKNOWN', is counted in NO total, and is WARNed by the export job.
-- The ELSE arm is deliberately loud rather than a real value: a new product type must be classified
-- by a human, not absorbed into impressions by a default.
--
-- CLICKS sum across all three DELIVERY units (a solus click is a real click the publisher reports)
-- but never across rate rows. That asymmetry is why clicks are not gated on the impression flag.
--
-- SOME ROWS CARRY CLICKS WITH NULL IMPRESSIONS and must never be dropped - the publisher reports one
-- impression count for a shared eNews send or a paired left/right side-bar position and attributes
-- clicks to each half. A NULL there means "not separately reported", never zero.
--
-- CAMPAIGN comes from the META table, joined on the publisher string, because the export carries a
-- job number but no campaign. A publisher with no meta row therefore resolves to a NULL campaign,
-- renders nowhere, and is WARNed by name - see sql/26 and the job's audit.
--
-- GRAIN OUT: campaign x publisher x period x placement, one row per reported measure, plus one row
-- per publisher-reported RATE. NO SPEND, NO MARKET, NO DAY: monthly aggregates that must never
-- reach pm_delivery, the blended KPI band or any CPM/CPC figure.
CREATE OR REPLACE VIEW `bidbrain-analytics.client_schneider.publisher_delivery` AS
WITH src AS (
  SELECT
    LOWER(TRIM(publisher))                                       AS pub_key,
    TRIM(publisher)                                              AS publisher,
    report_month,
    LOWER(TRIM(COALESCE(product_type, '')))                      AS product_type,
    NULLIF(TRIM(COALESCE(placement_name, '')), '')               AS placement,
    start_date, end_date,
    impressions, clicks, sends, open_rate, viewability, booked_views, delivered_views
  FROM `bidbrain-analytics.client_schneider.seed_publisher_reports`
  -- a wholly blank line (a trailing newline in a hand-edited export) is not a data point
  WHERE COALESCE(TRIM(publisher), '') <> '' AND report_month IS NOT NULL
),
meta AS (
  SELECT LOWER(TRIM(publisher)) AS pub_key, TRIM(internal_campaign_id) AS campaign
  FROM `bidbrain-analytics.client_schneider.seed_publisher_report_meta`
  WHERE COALESCE(TRIM(publisher), '') <> ''
),
-- A publisher that reports CONTENT separately (Capital Brief) presents its report as content vs
-- advertising, and that split is what its card shows month by month. Every other publisher presents
-- its report by product. Derived from the data rather than hardcoded per publisher, so a second
-- content-reporting publisher gets the same treatment without a code change.
content_pubs AS (
  SELECT DISTINCT pub_key FROM src WHERE STARTS_WITH(product_type, 'content_')
),
typed AS (
  SELECT
    s.*,
    CASE s.product_type
      WHEN 'content_newsletter' THEN 'impressions'
      WHEN 'content_web'        THEN 'impressions'
      WHEN 'adv_newsletter'     THEN 'impressions'
      WHEN 'adv_display'        THEN 'impressions'
      WHEN 'solus_edm'          THEN 'sends'
      WHEN 'sponsored_article'  THEN 'article_views'
      ELSE 'UNKNOWN'
    END AS unit,
    CASE
      WHEN STARTS_WITH(s.product_type, 'content_')    THEN 'Content distribution'
      WHEN s.product_type = 'solus_edm'               THEN 'Solus eDM'
      WHEN s.product_type = 'sponsored_article'       THEN 'Featured Content Plus'
      WHEN s.pub_key IN (SELECT pub_key FROM content_pubs) THEN 'Advertising'
      WHEN s.product_type = 'adv_newsletter'          THEN 'eNewsletter'
      WHEN s.product_type = 'adv_display'             THEN 'Website display'
      ELSE 'Unclassified'
    END AS placement_group
  FROM src s
),
delivery AS (
  SELECT
    m.campaign,
    t.publisher,
    FORMAT_DATE('%B %Y', t.report_month)                         AS period_label,
    COALESCE(t.start_date, t.report_month)                       AS period_start,
    COALESCE(t.end_date, LAST_DAY(t.report_month))               AS period_end,
    t.placement_group,
    t.placement,
    t.unit,
    CAST(NULL AS STRING)                                         AS metric,
    -- Pre-split measures, so a consumer physically cannot add a send to an impression by summing
    -- one column. Each is NULL - never 0 - outside its own unit: 0 would assert a measured zero.
    IF(t.unit = 'impressions',   t.impressions,     NULL)        AS impressions,
    IF(t.unit = 'sends',         t.sends,           NULL)        AS sends,
    IF(t.unit = 'article_views', t.delivered_views, NULL)        AS article_views,
    CAST(NULL AS FLOAT64)                                        AS rate_value,
    t.clicks,
    IF(t.unit = 'article_views', t.booked_views,    NULL)        AS booked_quantity,
    CAST(NULL AS STRING)                                         AS note
  FROM typed t
  LEFT JOIN meta m USING (pub_key)
),
-- Publisher-reported RATES, one row per publisher x period x metric. The export repeats a rate on
-- every row it applies to (Capital Brief states one open rate against both its newsletter lines),
-- so they are de-duplicated here rather than averaged downstream. A rate is attached to a placement
-- group ONLY when every row carrying it sits in one group - otherwise it belongs to the publisher's
-- whole month and carrying a group would weight it against a fraction of its own delivery.
rate_src AS (
  SELECT pub_key, publisher, report_month, placement_group,
         CASE WHEN product_type = 'solus_edm' THEN 'solus_open_rate'
              ELSE 'newsletter_open_rate' END AS metric,
         open_rate AS pct
  FROM typed WHERE open_rate IS NOT NULL
  UNION ALL
  SELECT pub_key, publisher, report_month, placement_group, 'display_viewability', viewability
  FROM typed WHERE viewability IS NOT NULL
),
rates AS (
  SELECT
    m.campaign,
    r.publisher,
    FORMAT_DATE('%B %Y', r.report_month)                         AS period_label,
    DATE_TRUNC(r.report_month, MONTH)                            AS period_start,
    LAST_DAY(r.report_month)                                     AS period_end,
    IF(COUNT(DISTINCT r.placement_group) = 1, ANY_VALUE(r.placement_group), NULL) AS placement_group,
    CAST(NULL AS STRING)                                         AS placement,
    'rate'                                                       AS unit,
    r.metric,
    CAST(NULL AS INT64) AS impressions, CAST(NULL AS INT64) AS sends,
    CAST(NULL AS INT64) AS article_views,
    -- the export states rates as PERCENTAGES (54, 26.75); everything downstream expects a fraction
    MAX(r.pct) / 100                                             AS rate_value,
    CAST(NULL AS INT64) AS clicks, CAST(NULL AS INT64) AS booked_quantity,
    CAST(NULL AS STRING) AS note
  FROM rate_src r
  LEFT JOIN meta m USING (pub_key)
  GROUP BY m.campaign, r.publisher, r.report_month, r.metric
)
SELECT * FROM delivery
UNION ALL
SELECT * FROM rates;
