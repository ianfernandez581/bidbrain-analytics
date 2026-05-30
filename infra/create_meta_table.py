"""
One-time setup: create the Meta/Facebook performance table.

Grain: ONE ROW per (ad_id x metric_date). Most granular level Meta exposes
without breakdown dimensions, so you can roll up to adset / campaign / account
in SQL and join creative metadata for creative-level views.

NO breakdown dimensions (publisher_platform, age, gender, country, device...)
are stored here -- any of those would multiply rows and change the grain.
Platform/demographic splits go in a separate table later.

Lives in raw_windsor alongside perf_the_trade_desk.

Run:  python create_meta_table.py
Idempotent (exists_ok=True) -- but note it CREATES, it does not ALTER. If the
table already exists from an earlier (narrower) version, drop it first (it's
empty) so the new columns take effect:
    bq rm -f -t bidbrain-analytics:raw_windsor.perf_meta
"""
from google.cloud import bigquery

client = bigquery.Client(project="bidbrain-analytics")

schema = [
    # ---- Identifiers / dimensions ----
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, always 'meta'"),
    bigquery.SchemaField("account_id", "STRING"),
    bigquery.SchemaField("account_name", "STRING"),
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("campaign_name", "STRING", description="Windsor 'campaign'"),
    bigquery.SchemaField("objective", "STRING",
        description="Objective, e.g. OUTCOME_LEADS / OUTCOME_TRAFFIC"),
    bigquery.SchemaField("adset_id", "STRING"),
    bigquery.SchemaField("adset_name", "STRING"),
    bigquery.SchemaField("ad_id", "STRING", mode="REQUIRED",
        description="Finest grain; part of MERGE key"),
    bigquery.SchemaField("ad_name", "STRING"),
    bigquery.SchemaField("effective_status", "STRING",
        description="Effective delivery status (ACTIVE, PAUSED, ...)"),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, derived from account/campaign/ad names"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. 'ad-assembly' / '100-digital'"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of metrics; part of MERGE key"),
    bigquery.SchemaField("currency", "STRING", description="Windsor account_currency"),
    bigquery.SchemaField("campaign_spend_cap", "NUMERIC",
        description="Campaign spend cap (current-state config)"),

    # ---- Delivery & cost ----
    bigquery.SchemaField("impressions", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("reach", "INT64", description="Unique people who saw the ad"),
    bigquery.SchemaField("frequency", "FLOAT64", description="impressions / reach"),
    bigquery.SchemaField("cost", "NUMERIC", mode="REQUIRED",
        description="Windsor 'spend', already in account currency (not micros)"),
    bigquery.SchemaField("cpc", "NUMERIC", description="Meta-computed cost per click (all)"),
    bigquery.SchemaField("cpm", "NUMERIC", description="Meta-computed cost per 1k impressions"),
    bigquery.SchemaField("cpp", "NUMERIC", description="Meta-computed cost per 1k reached"),

    # ---- Clicks: all ----
    bigquery.SchemaField("clicks", "INT64", mode="REQUIRED",
        description="All clicks (incl. reactions, comments, expands)"),
    bigquery.SchemaField("unique_clicks", "INT64"),

    # ---- Clicks: link (use these for CTR/CPC) ----
    bigquery.SchemaField("link_clicks", "INT64"),
    bigquery.SchemaField("link_clicks_actions", "INT64",
        description="actions_link_click (alt path; usually == link_clicks)"),
    bigquery.SchemaField("unique_link_clicks", "INT64",
        description="unique_actions_link_click"),
    bigquery.SchemaField("unique_link_clicks_ctr", "FLOAT64",
        description="Windsor PERCENT scale -- verify 0-1 vs 0-100 on first load"),
    bigquery.SchemaField("cost_per_link_click", "NUMERIC"),
    bigquery.SchemaField("cost_per_unique_link_click", "NUMERIC"),

    # ---- Clicks: outbound ----
    bigquery.SchemaField("outbound_clicks", "INT64"),
    bigquery.SchemaField("unique_outbound_clicks", "INT64"),
    bigquery.SchemaField("outbound_ctr", "FLOAT64", description="Windsor PERCENT scale"),
    bigquery.SchemaField("unique_outbound_ctr", "FLOAT64", description="Windsor PERCENT scale"),
    bigquery.SchemaField("cost_per_outbound_click", "NUMERIC"),
    bigquery.SchemaField("cost_per_unique_outbound_click", "NUMERIC"),

    # ---- Engagement ----
    bigquery.SchemaField("post_engagement", "INT64"),
    bigquery.SchemaField("unique_post_engagement", "INT64"),
    bigquery.SchemaField("page_engagement", "INT64"),
    bigquery.SchemaField("reactions", "INT64"),
    bigquery.SchemaField("comments", "INT64"),
    bigquery.SchemaField("shares", "INT64", description="Windsor actions_post"),
    bigquery.SchemaField("saves", "INT64"),
    bigquery.SchemaField("video_3s_views", "INT64", description="3-second video plays"),

    # ---- Awareness / brand ----
    bigquery.SchemaField("est_ad_recall_lift", "NUMERIC",
        description="estimated_ad_recallers; only on awareness-type objectives"),
    bigquery.SchemaField("est_ad_recall_rate", "FLOAT64",
        description="estimated_ad_recall_rate (Windsor PERCENT scale)"),
    bigquery.SchemaField("instagram_profile_visits", "INT64"),

    # ---- Leads ----
    bigquery.SchemaField("leads", "INT64",
        description="All leads: FB forms + Messenger + off-FB pixel (actions_lead)"),
    bigquery.SchemaField("leads_website", "INT64", description="Website/pixel leads"),
    bigquery.SchemaField("leads_onfacebook", "INT64", description="On-Facebook leads"),
    bigquery.SchemaField("unique_leads", "INT64", description="unique_actions_lead"),
    bigquery.SchemaField("cost_per_lead", "NUMERIC",
        description="cost_per_action_type_lead"),

    # ---- Conversions & value (ecom; null for lead-gen) ----
    bigquery.SchemaField("landing_page_views", "INT64"),
    bigquery.SchemaField("add_to_cart", "INT64"),
    bigquery.SchemaField("initiate_checkout", "INT64"),
    bigquery.SchemaField("purchases", "INT64", description="Omni purchases"),
    bigquery.SchemaField("registrations", "INT64"),
    bigquery.SchemaField("purchase_value", "NUMERIC",
        description="action_values_omni_purchase"),
    bigquery.SchemaField("purchase_roas", "NUMERIC",
        description="purchase_roas_omni_purchase (web+app+offline)"),
    bigquery.SchemaField("purchase_roas_website", "NUMERIC",
        description="website_purchase_roas_offsite_conversion_fb_pixel_purchase"),

    # ---- Video funnel ----
    bigquery.SchemaField("video_starts", "INT64", description="video_play_actions"),
    bigquery.SchemaField("video_25", "INT64"),
    bigquery.SchemaField("video_50", "INT64"),
    bigquery.SchemaField("video_75", "INT64"),
    bigquery.SchemaField("video_95", "INT64"),
    bigquery.SchemaField("video_completes", "INT64", description="watched at 100%"),
    bigquery.SchemaField("thruplays", "INT64",
        description="Played to completion or >=15s -- Meta's preferred video metric"),
    bigquery.SchemaField("video_avg_watch_time", "FLOAT64",
        description="Average video play time, seconds"),

    # ---- Optimization signals ----
    bigquery.SchemaField("quality_ranking", "STRING"),
    bigquery.SchemaField("engagement_rate_ranking", "STRING"),
    bigquery.SchemaField("conversion_rate_ranking", "STRING"),

    # ---- Creative metadata ----
    bigquery.SchemaField("creative_id", "STRING"),
    bigquery.SchemaField("creative_thumbnail_url", "STRING", description="thumbnail_url"),
    bigquery.SchemaField("ig_thumbnail_url", "STRING",
        description="effective_instagram_media__thumbnail_url"),
    bigquery.SchemaField("placement_thumbnail_url", "STRING",
        description="placement_ad_thumbnail_url"),
    bigquery.SchemaField("creative_title", "STRING", description="Windsor 'title'"),
    bigquery.SchemaField("creative_body", "STRING", description="Windsor 'body'"),
    bigquery.SchemaField("creative_link_url", "STRING",
        description="Windsor 'link_url' (ad creative link URL)"),
    bigquery.SchemaField("destination_url", "STRING",
        description="Windsor 'link' (where the ad clicks through to)"),

    # ---- Provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.facebook'"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original (flat) Windsor row, incl. datasource, for fidelity"),
]

table_id = "bidbrain-analytics.raw_windsor.perf_meta"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["campaign_id", "ad_id"]
table.description = "Meta/Facebook Ads performance, one row per (ad x date), via Windsor.ai"

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")