"""
One-time setup: create the Google Ads performance table (perf_google_ads).

Grain: ONE ROW per (customer_id x metric_date x campaign_id) -- i.e. campaign-level
daily delivery for Google Ads. This is the ad-platform spine that joins back to
perf_ga4 / perf_meta / perf_the_trade_desk: Google Ads tells you what each campaign
DELIVERED (impressions, clicks, spend) and self-reported conversions per day; GA4
tells you what the click then did on-site.

Sibling of create_ga4_table.py, but simpler: the Windsor google_ads connector has NO
GA4-style 9-dim/10-metric cap, so the loader is single-pass (see google_ads_loader.py),
and the grain is plain campaign x date (no source/medium/channel split).

METRICS ARE ADDITIVE BASE ONLY. Do NOT add ctr / average_cpc / cpm / cost_per_* /
*_rate / roas as columns -- they're non-additive and break when summed across days or
campaigns. Store numerator + denominator and derive in client SQL:
    ctr  = SUM(clicks) / SUM(impressions)
    cpc  = SUM(spend)  / SUM(clicks)
    cpm  = SUM(spend)  / SUM(impressions) * 1000
    cpa  = SUM(spend)  / NULLIF(SUM(conversions), 0)
    cvr  = SUM(conversions) / SUM(clicks)
    roas = SUM(conversions_value) / NULLIF(SUM(spend), 0)

ONE COST FIELD ONLY: `spend` (Google Ads cost). Windsor also exposes cost / cost_micros
/ totalcost variants -- those are deliberately NOT stored (duplicates).

conversions / conversions_value are NUMERIC, never INT: Google Ads conversions can be
fractional (conversion modeling / fractional attribution).

Lives in raw_windsor alongside perf_ga4 / perf_meta / perf_the_trade_desk.

Run:  python windsor_data_pull/google_ads/create_google_ads_table.py   (after create_dataset.py)
Idempotent (exists_ok=True) -- but note it CREATES, it does not ALTER. If the table
already exists from an earlier (narrower) version, drop it first (it's empty) so the new
columns take effect:
    bq rm -f -t bidbrain-analytics:raw_windsor.perf_google_ads
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT, location="australia-southeast1")

schema = [
    # ---- Identifiers / tenant ----
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, always 'google_ads'"),
    bigquery.SchemaField("customer_id", "STRING", mode="REQUIRED",
        description="Google Ads customer id (Windsor 'account_id', hyphenated e.g. 105-440-7474); tenant key + part of MERGE key"),
    bigquery.SchemaField("account_name", "STRING",
        description="Google Ads account display name (Windsor 'account_name')"),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, from CUSTOMER_TO_CLIENT / keyword fallback on account_name+campaign"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. '100-digital' / 'ad-assembly'"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of metrics (Windsor 'date', normalised to YYYY-MM-DD); MERGE key + partition field"),

    # ---- Campaign grain ----
    bigquery.SchemaField("campaign_id", "STRING", mode="REQUIRED",
        description="Google Ads campaign id (Windsor 'campaign_id'). MERGE key."),
    bigquery.SchemaField("campaign_name", "STRING",
        description="Google Ads campaign name (Windsor 'campaign')"),
    bigquery.SchemaField("campaign_type", "STRING",
        description="Advertising channel type (Windsor 'campaign_type': SEARCH / PERFORMANCE_MAX / SHOPPING / ...). "
                    "Attribute, NOT a key -- functionally determined by campaign_id."),
    bigquery.SchemaField("currency_code", "STRING",
        description="Account currency (Windsor 'currency_code', e.g. AUD)"),

    # ---- Metrics: ADDITIVE BASE ONLY (derive ctr/cpc/cpm/cpa/cvr/roas in SQL; see docstring) ----
    bigquery.SchemaField("impressions", "INT64"),
    bigquery.SchemaField("clicks", "INT64"),
    bigquery.SchemaField("spend", "NUMERIC",
        description="Google Ads cost (Windsor 'spend'). The ONLY cost field stored -- ignore cost/cost_micros/totalcost"),
    bigquery.SchemaField("conversions", "NUMERIC",
        description="Google Ads conversions (NUMERIC: fractional under conversion modeling / attribution)"),
    bigquery.SchemaField("conversions_value", "NUMERIC",
        description="Total conversion value, in the account's currency"),

    # ---- Provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.google_ads' (our provenance tag; Windsor's own source/datasource constants are not stored)"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original Windsor row, for fidelity"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.perf_google_ads"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["customer_id", "campaign_type"]
table.description = ("Google Ads campaign-level daily delivery, one row per "
                     "(customer x date x campaign), via Windsor.ai")

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")
