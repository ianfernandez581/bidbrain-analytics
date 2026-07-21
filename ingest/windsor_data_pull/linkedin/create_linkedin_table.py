"""
One-time setup: create the LinkedIn Ads performance table (perf_linkedin).

Grain: ONE ROW per (account_id x creative_id x metric_date) -- creative-level daily
delivery for LinkedIn Ads. Confirmed by probe_linkedin_fields.py against the blended
/all endpoint: campaign_id (103 distinct) and creative_id (360 distinct) both populate
100%, one row per (account, campaign, creative, date) cell -- so we key on the finest
grain (creative_id) and let campaign / campaign-group ride along as attributes. This is
the LinkedIn sibling of perf_reddit / perf_meta / perf_the_trade_desk: LinkedIn tells you
what each ad DELIVERED (impressions, clicks, spend), the leads its lead-gen forms captured
(one_click_leads / lead_form_opens) and the site conversions its pixel attributed, per day.

Sibling of create_reddit_table.py (ad-grain, ride-along campaign attributes, additive-base
discipline, native-currency spend + stored `currency`). Two LinkedIn-specific realities the
loader handles (see linkedin_loader.py):
  * TWO-PASS FETCH. LinkedIn's adAnalytics API caps a request at 20 fields, so each chunk is
    fetched in two <=20-field passes (delivery+leads, then engagement+video) merged on
    (account_id, creative_id, date) -- the GA4 two-pass pattern.
  * campaign_group_id comes back ALL NULL on /all (the group NAME populates), so we store
    campaign_group_name and OMIT the id.

METRICS ARE ADDITIVE BASE ONLY. Do NOT add ctr / cpc / cpm / cpl / *_cvr / engagement_rate /
frequency / video_completion_rate / roas as columns -- they're non-additive and break when
summed across days / creatives. Store numerator + denominator and derive in client SQL:
    ctr  = SUM(clicks) / NULLIF(SUM(impressions), 0)
    cpc  = SUM(spend)  / NULLIF(SUM(clicks), 0)
    cpm  = SUM(spend)  / NULLIF(SUM(impressions), 0) * 1000
    cpl  = SUM(spend)  / NULLIF(SUM(one_click_leads), 0)
    video_completion_rate = SUM(video_completions) / NULLIF(SUM(video_starts), 0)
    frequency = SUM(impressions) / NULLIF(SUM(reach), 0)   -- approximate; daily reach is not
                                                              truly additive across days

ONE COST FIELD ONLY: `spend` (LinkedIn cost, in account currency). Windsor also exposes a
`totalcost` variant -- deliberately NOT stored (duplicate). We do NOT store Windsor's own
source / datasource constants -- our provenance is set in `source`.

reach (approximate_unique_impressions) is NON-ADDITIVE across days (unique members) and is
only available for windows <= 92 days from the Windsor API -- derive frequency in SQL, never
SUM reach for a period total. The loader's <=30-day chunks stay comfortably under the 92-day cap.

currency is stored (ISO-4217, e.g. AUD / SGD / USD) so client views can FX to the client's
reporting currency. LinkedIn spend comes back in the account's NATIVE currency (probe saw
AUD, SGD and USD across the connected accounts), not USD -- getting this wrong is the silent
bug that has bitten other pipelines, so the column is non-negotiable.

Lives in raw_windsor alongside perf_reddit / perf_meta / perf_google_ads / perf_the_trade_desk /
perf_ga4.

Run:  python windsor_data_pull/linkedin/create_linkedin_table.py   (after create_dataset.py)
Idempotent (exists_ok=True) -- but note it CREATES, it does not ALTER. If the table already
exists from an earlier (narrower) version, drop it first (it's empty) so the new columns take
effect:
    bq rm -f -t bidbrain-analytics:raw_windsor.perf_linkedin
"""
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
RAW_DATASET = "raw_windsor"

client = bigquery.Client(project=PROJECT, location="australia-southeast1")

schema = [
    # ---- Identity / grain ----
    bigquery.SchemaField("platform", "STRING", mode="REQUIRED",
        description="Source platform, always 'linkedin'"),
    bigquery.SchemaField("account_id", "STRING", mode="REQUIRED",
        description="LinkedIn ad account id (Windsor 'account_id', numeric string e.g. "
                    "510177932); tenant key + part of MERGE key"),
    bigquery.SchemaField("account_name", "STRING",
        description="LinkedIn ad account display name (Windsor 'account_name')"),
    bigquery.SchemaField("currency", "STRING",
        description="Account currency (ISO-4217, Windsor 'currency', e.g. AUD/SGD/USD). "
                    "Needed for FX in client views -- LinkedIn spend is in this native currency."),
    bigquery.SchemaField("campaign_group_name", "STRING",
        description="LinkedIn campaign-group name (Windsor 'campaign_group_name'). Attribute. "
                    "NOTE: 'campaign_group_id' comes back ALL NULL on /all, so it is not stored."),
    bigquery.SchemaField("campaign_id", "STRING",
        description="LinkedIn campaign id (Windsor 'campaign_id'). Attribute, NOT a key -- "
                    "functionally determined by creative_id. Clustering field."),
    bigquery.SchemaField("campaign_name", "STRING",
        description="LinkedIn campaign name (Windsor 'campaign'). The client filter keys on this "
                    "(e.g. campaign_name LIKE 'MONGODB_%')."),
    bigquery.SchemaField("campaign_type", "STRING",
        description="Campaign type (Windsor 'campaign_type', e.g. SPONSORED_UPDATES). Attribute."),
    bigquery.SchemaField("objective_type", "STRING",
        description="Objective (Windsor 'objective_type', e.g. LEAD_GENERATION / WEBSITE_VISIT / "
                    "BRAND_AWARENESS). Attribute."),
    bigquery.SchemaField("campaign_status", "STRING",
        description="Campaign status (Windsor 'campaign_status', e.g. ACTIVE / COMPLETED). Attribute."),
    bigquery.SchemaField("creative_id", "STRING", mode="REQUIRED",
        description="LinkedIn creative id (Windsor 'creative_id'). Finest grain; part of MERGE key."),
    bigquery.SchemaField("creative_status", "STRING",
        description="Creative status (Windsor 'creative_status'). Attribute."),
    bigquery.SchemaField("landing_page", "STRING",
        description="Creative landing-page URL (Windsor 'landing_page'). Attribute."),
    bigquery.SchemaField("share_title", "STRING",
        description="Creative headline / share title (Windsor 'share_title'). Attribute."),
    bigquery.SchemaField("client_slug", "STRING",
        description="Internal client slug, from LINKEDIN_ACCOUNT_TO_CLIENT / keyword fallback "
                    "on account_name+campaign_name"),
    bigquery.SchemaField("agency_slug", "STRING",
        description="Internal agency slug, e.g. 'transmission' / '100-digital'"),
    bigquery.SchemaField("metric_date", "DATE", mode="REQUIRED",
        description="Date of metrics (Windsor 'date', normalised to YYYY-MM-DD); MERGE key + "
                    "partition field"),

    # ---- Delivery: ADDITIVE BASE ONLY (derive ctr/cpc/cpm/cpl/cvr in SQL; see docstring) ----
    bigquery.SchemaField("impressions", "INT64"),
    bigquery.SchemaField("clicks", "INT64",
        description="Chargeable clicks (Windsor 'clicks')"),
    bigquery.SchemaField("spend", "NUMERIC",
        description="LinkedIn cost (Windsor 'spend'), in account currency. The ONLY cost field "
                    "stored -- ignore totalcost"),
    bigquery.SchemaField("reach", "INT64",
        description="Approximate unique impressions / members reached (Windsor "
                    "'approximate_unique_impressions'). NON-ADDITIVE across days -- derive frequency "
                    "in SQL, never SUM reach for a period total. Windsor caps this to <=92-day windows."),
    bigquery.SchemaField("landing_page_clicks", "INT64",
        description="Clicks to the landing page (Windsor 'landingpageclicks')"),

    # ---- Engagement (additive) ----
    bigquery.SchemaField("engagements", "INT64", description="Windsor 'engagements'"),
    bigquery.SchemaField("likes", "INT64", description="Windsor 'likes'"),
    bigquery.SchemaField("comments", "INT64", description="Windsor 'comments'"),
    bigquery.SchemaField("shares", "INT64", description="Windsor 'shares'"),
    bigquery.SchemaField("follows", "INT64", description="Windsor 'follows'"),

    # ---- Lead-gen forms (additive counts) ----
    bigquery.SchemaField("one_click_leads", "INT64",
        description="LinkedIn Lead Gen Form submissions (Windsor 'oneclickleads'). The lead-gen "
                    "delivery number for LEAD_GENERATION campaigns (e.g. MongoDB AWS Immersion Day)."),
    bigquery.SchemaField("lead_form_opens", "INT64",
        description="LinkedIn Lead Gen Form opens (Windsor 'oneclickleadformopens'). Funnel top for one_click_leads."),

    # ---- Site conversions (additive, NUMERIC -- LinkedIn can report modeled/fractional) ----
    bigquery.SchemaField("ext_website_conversions", "NUMERIC",
        description="External website conversions, all (Windsor 'externalwebsiteconversions')"),
    bigquery.SchemaField("ext_website_post_click_conversions", "NUMERIC",
        description="Post-click external website conversions (Windsor 'externalwebsitepostclickconversions')"),
    bigquery.SchemaField("ext_website_post_view_conversions", "NUMERIC",
        description="Post-view external website conversions (Windsor 'externalwebsitepostviewconversions')"),

    # ---- Video funnel (additive counts; derive rates in SQL) ----
    bigquery.SchemaField("video_views", "INT64", description="Windsor 'video_views'"),
    bigquery.SchemaField("video_starts", "INT64", description="Windsor 'video_starts'"),
    bigquery.SchemaField("video_completions", "INT64", description="Windsor 'video_completions'"),
    bigquery.SchemaField("video_q25", "INT64", description="Video watched to 25% (Windsor 'quartile_1')"),
    bigquery.SchemaField("video_q50", "INT64", description="Video watched to 50% (Windsor 'quartile_2')"),
    bigquery.SchemaField("video_q75", "INT64", description="Video watched to 75% (Windsor 'quartile_3')"),

    # ---- Provenance ----
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("source", "STRING", mode="REQUIRED",
        description="'windsor.linkedin' (our provenance tag; Windsor's own source/datasource "
                    "constants are not stored)"),
    bigquery.SchemaField("raw_row", "JSON",
        description="Full merged Windsor row (both passes), for fidelity -- every un-promoted "
                    "field stays here, so skipping a column is reversible"),
]

table_id = f"{PROJECT}.{RAW_DATASET}.perf_linkedin"
table = bigquery.Table(table_id, schema=schema)
table.time_partitioning = bigquery.TimePartitioning(
    type_=bigquery.TimePartitioningType.DAY,
    field="metric_date",
)
table.clustering_fields = ["account_id", "campaign_id"]
table.description = ("LinkedIn Ads creative-level daily delivery, one row per "
                     "(account x creative x date), via Windsor.ai (/all, linkedin__ prefix)")

table = client.create_table(table, exists_ok=True)
print(f"Created {table_id}")
print(f"  Partitioned by: {table.time_partitioning.field}")
print(f"  Clustered by:   {table.clustering_fields}")
print(f"  Columns:        {len(table.schema)}")
