"""
One-time setup: create the Reddit Ads performance table (perf_reddit).

Grain: ONE ROW per (account_id x ad_id x metric_date) -- ad-level daily delivery for
Reddit Ads. Confirmed by probe_reddit_fields.py: the blended /all endpoint returns the
full Reddit hierarchy (campaign_id / ad_group_id / ad_id all populated, never the GA4
nulling pattern), so we key on the finest grain (ad_id) and let campaign / ad-group ride
along as attributes. This is the ad-platform spine that joins back to perf_ga4 /
perf_meta / perf_google_ads / perf_the_trade_desk: Reddit tells you what each ad
DELIVERED (impressions, clicks, spend) and self-reported conversions per day; GA4
(perf_ga4) tells you what the click then did on-site.

Sibling of create_meta_table.py (same ad grain, ride-along campaign/ad-group attributes)
and create_google_ads_table.py (additive-base discipline, NUMERIC conversions). The
Windsor /all connector has NO GA4-style 9-dim/10-metric cap, so the loader is single-pass
(see reddit_loader.py).

METRICS ARE ADDITIVE BASE ONLY. Do NOT add ctr / cpc / cpm / cpv / ecpm / *_cvr / *_ecpa
/ frequency / video_completion_rate / roas as columns -- they're non-additive and break
when summed across days / ads. Store numerator + denominator and derive in client SQL:
    ctr  = SUM(clicks) / NULLIF(SUM(impressions), 0)
    cpc  = SUM(spend)  / NULLIF(SUM(clicks), 0)
    cpm  = SUM(spend)  / NULLIF(SUM(impressions), 0) * 1000
    cpl  = SUM(spend)  / NULLIF(SUM(lead_clicks) + SUM(lead_views), 0)
    lead_cvr = (SUM(lead_clicks) + SUM(lead_views)) / NULLIF(SUM(clicks), 0)
    video_completion_rate = SUM(video_completes) / NULLIF(SUM(video_starts), 0)
    frequency = SUM(impressions) / NULLIF(SUM(reach), 0)   -- approximate; daily reach is
                                                              not truly additive across days

ONE COST FIELD ONLY: `spend` (Reddit cost, in account currency). Windsor also exposes a
`totalcost` variant -- that is deliberately NOT stored (duplicate). We also do NOT store
Windsor's own source / datasource constants -- our provenance is set in `source`.

reach is NON-ADDITIVE across days (unique people, like GA4 total_users) -- derive
frequency in SQL, never SUM reach for a period total.

CONVERSIONS ARE NUMERIC, never INT: Reddit reports fractional conversions under modeling /
attribution. The click/view split is kept as separate columns -- never sum click + view
into one number; derive in SQL.

account_currency is stored (ISO-4217, e.g. AUD) so client views can FX to the client's
reporting currency. Reddit spend comes back in the account's NATIVE currency (probe
confirmed AUD for the ResetData account), not USD.

Lives in raw_windsor alongside perf_ga4 / perf_meta / perf_google_ads / perf_the_trade_desk.

Run:  python windsor_data_pull/reddit/create_reddit_table.py   (after create_dataset.py)
Idempotent (exists_ok=True) -- but note it CREATES, it does not ALTER. If the table
already exists from an earlier (narrower) version, drop it first (it's empty) so the new
columns take effect:
    bq rm -f -t bidbrain-analytics:raw_windsor.perf_reddit
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT, location="australia-southeast1")

schema = [
    # ---- Identity / grain ----
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, always 'reddit'"),
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED",
        description="Reddit ad account id (Windsor 'account_id', opaque alphanumeric e.g. "
                    "a2_igd0szmw7roq -- NOT numeric); tenant key + part of MERGE key"),
    bigquery.SchemaField("account_name", "STRING",
        description="Reddit ad account display name (Windsor 'account_name')"),
    bigquery.SchemaField("account_currency", "STRING",
        description="Account currency (ISO-4217, Windsor 'account_currency', e.g. AUD). "
                    "Needed for FX in client views -- Reddit spend is in this native currency."),
    bigquery.SchemaField("campaign_id", "STRING",
        description="Reddit campaign id (Windsor 'campaign_id'). Attribute, NOT a key -- "
                    "functionally determined by ad_id. Clustering field."),
    bigquery.SchemaField("campaign_name", "STRING",
        description="Reddit campaign name (Windsor 'campaign_name'; identical to 'campaign')"),
    bigquery.SchemaField("campaign_objective", "STRING",
        description="Campaign objective (Windsor 'campaign_objective', e.g. CONVERSIONS / "
                    "TRAFFIC). Attribute, NOT a key."),
    bigquery.SchemaField("ad_group_id", "STRING",
        description="Reddit ad-group id (Windsor 'ad_group_id'). Attribute."),
    bigquery.SchemaField("ad_group_name", "STRING",
        description="Reddit ad-group name (Windsor 'ad_group_name')"),
    bigquery.SchemaField("ad_id", "STRING", mode="REQUIRED",
        description="Reddit ad id (Windsor 'ad_id'). Finest grain; part of MERGE key."),
    bigquery.SchemaField("ad_name", "STRING",
        description="Reddit ad name (Windsor 'ad_name')"),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, from REDDIT_ACCOUNT_TO_CLIENT / keyword fallback "
                    "on account_name+campaign_name"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. '100-digital' / 'ad-assembly'"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of metrics (Windsor 'date', normalised to YYYY-MM-DD); MERGE key + "
                    "partition field"),

    # ---- Delivery: ADDITIVE BASE ONLY (derive ctr/cpc/cpm/cpl/cvr in SQL; see docstring) ----
    bigquery.SchemaField("impressions", "INT64"),
    bigquery.SchemaField("clicks", "INT64"),
    bigquery.SchemaField("spend", "NUMERIC",
        description="Reddit cost (Windsor 'spend'), in account currency. The ONLY cost field "
                    "stored -- ignore totalcost"),
    bigquery.SchemaField("reach", "INT64",
        description="Unique people reached. NON-ADDITIVE across days (like GA4 total_users) -- "
                    "derive frequency in SQL, never SUM reach for a period total"),

    # ---- Engagement (additive) ----
    bigquery.SchemaField("upvotes", "INT64",
        description="Upvotes (Windsor 'upvotes'). NULL where Windsor doesn't surface Reddit "
                    "engagement for the account (the case at build time)."),
    bigquery.SchemaField("downvotes", "INT64", description="Downvotes (Windsor 'downvotes')"),
    bigquery.SchemaField("comment_submissions", "INT64",
        description="Comment submissions (Windsor 'comment_submissions')"),

    # ---- Video funnel (additive counts; derive rates in SQL) ----
    bigquery.SchemaField("video_starts", "INT64", description="Windsor 'video_started'"),
    bigquery.SchemaField("video_25", "INT64", description="Windsor 'video_watched_25_percent'"),
    bigquery.SchemaField("video_50", "INT64", description="Windsor 'video_watched_50_percent'"),
    bigquery.SchemaField("video_75", "INT64", description="Windsor 'video_watched_75_percent'"),
    bigquery.SchemaField("video_completes", "INT64",
        description="Watched to 100% (Windsor 'video_watched_100_percent')"),

    # ---- Conversions (additive, NUMERIC, click/view split -- never sum click+view together) ----
    bigquery.SchemaField("lead_clicks", "NUMERIC", description="Windsor 'conversion_lead_clicks'"),
    bigquery.SchemaField("lead_views", "NUMERIC", description="Windsor 'conversion_lead_views'"),
    bigquery.SchemaField("signup_clicks", "NUMERIC", description="Windsor 'conversion_sign_up_clicks'"),
    bigquery.SchemaField("signup_views", "NUMERIC", description="Windsor 'conversion_sign_up_views'"),
    bigquery.SchemaField("page_visit_clicks", "NUMERIC", description="Windsor 'conversion_page_visit_clicks'"),
    bigquery.SchemaField("page_visit_views", "NUMERIC", description="Windsor 'conversion_page_visit_views'"),
    bigquery.SchemaField("lead_total_value", "NUMERIC", description="Windsor 'lead_total_value'"),
    bigquery.SchemaField("signup_total_value", "NUMERIC", description="Windsor 'signup_total_value'"),

    # ---- Provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.reddit' (our provenance tag; Windsor's own source/datasource "
                    "constants are not stored)"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full original Windsor row, for fidelity (every un-promoted field stays "
                    "here, so skipping a column is reversible)"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.perf_reddit"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["account_id", "campaign_id"]
table.description = ("Reddit Ads ad-level daily delivery, one row per "
                     "(account x ad x date), via Windsor.ai (/all)")

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")
