r"""
One-time: create raw_windsor.geocon_salesforce_leads.

Lives in:  windsor_data_pull/salesforce/create_salesforce_table.py
Run once before salesforce_loader.py; the loader reads the live schema at runtime and never
creates or alters the table, so staging/MERGE cannot drift from it.

    .\.venv\Scripts\python.exe ingest\windsor_data_pull\salesforce\create_salesforce_table.py

WHY THIS TABLE IS CLIENT-SCOPED, not a shared perf_salesforce
--------------------------------------------------------------
Windsor holds exactly ONE Salesforce connection (salesforce__calvin@100.digital) and it is
Geocon's org - confirmed by its ACT property-law custom objects (crown lease, units plan,
block) and its campaign names (Gateway Braddon, Abode Hotels, Midnight Hotel). Naming the
table for the client follows raw_windsor.geocon_meta_breakdown / caltex_ttd_geo, and keeps
this out of the shared-mirror trap in AGENTS.md: a shared `SELECT *` mirror lets a third
party change your schema on the next tick. If a SECOND client's Salesforce is ever granted,
promote this to perf_salesforce with an org column rather than widening this one silently.

***NO PII IS INGESTED, AND THAT IS DELIBERATE.***
The Salesforce lead object exposes 227 fields including name, email, phone and date of birth.
The dashboard needs COUNTS BY DAY AND DEVELOPMENT and nothing else, so this table carries the
lead id, its created timestamp, the project/development it belongs to, and its source/status.
Every personal field is left in Salesforce. Do not add one "just in case": geocon.json is
served to the client's browser, so anything landing here is one view away from being published.
(Precedent: client_schneider/sql/17_stg_salesforce drops phone/email; client_cloudflare gates
its per-lead table behind BB_INTERNAL and still ships the numbers in the payload.)
"""
from google.cloud import bigquery

PROJECT_ID = "bidbrain-analytics"
DATASET    = "raw_windsor"
TABLE      = "geocon_salesforce_leads"
LOCATION   = "australia-southeast1"

SCHEMA = [
    # --- key ---------------------------------------------------------------------------------
    bigquery.SchemaField("lead_id", "STRING", mode="REQUIRED",
                         description="Salesforce Lead.Id (18-char). The MERGE key - one row per lead."),
    # --- when --------------------------------------------------------------------------------
    bigquery.SchemaField("created_at", "TIMESTAMP",
                         description="Lead.CreatedDate, UTC. Windsor returns +0000."),
    bigquery.SchemaField("created_date", "DATE",
                         description="DATE(created_at) in AUSTRALIA/SYDNEY - the day the enquiry "
                                     "was made locally. Partition column. Derived in the loader so "
                                     "every consumer agrees; a UTC date puts a 9am Canberra enquiry "
                                     "on the previous day for 10 hours of every day."),
    # --- what it is about --------------------------------------------------------------------
    bigquery.SchemaField("project_id", "STRING",
                         description="Project_of_Interest__c - the Project__c record id. The "
                                     "STABLE key; project_name is its label and can be renamed."),
    bigquery.SchemaField("project_name", "STRING",
                         description="Project_of_Interest_Text__c, e.g. 'Gateway', 'The Grande'. "
                                     "NOTE: ONE 'Gateway' record covers BOTH Gateway Braddon and "
                                     "Northbourne Gateway - see sql/13_stg_salesforce.sql."),
    bigquery.SchemaField("development_name", "STRING",
                         description="Development_Name__c. Agrees with project_name on ~95% of "
                                     "rows; carried as a cross-check, never as the primary key."),
    # --- how it arrived ----------------------------------------------------------------------
    bigquery.SchemaField("lead_source", "STRING",
                         description="Lead.LeadSource, e.g. 'Project Landing Page', 'Facebook'. "
                                     "COARSE - it names a channel family, never a campaign, so it "
                                     "cannot attribute a lead to an ad."),
    bigquery.SchemaField("lead_status", "STRING",
                         description="Lead.Status - Geocon's own funnel (Engaged / Qualified / "
                                     "Lost / Assigned / Converted). NOT the IsConverted flag."),
    # --- provenance --------------------------------------------------------------------------
    bigquery.SchemaField("client_slug", "STRING", description="Registry key. Always 'geocon' here."),
    bigquery.SchemaField("agency_slug", "STRING", description="Always '100-digital' here."),
    bigquery.SchemaField("source", "STRING", description="Always 'windsor_salesforce'."),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", description="When this row was last MERGEd."),
]


def main():
    bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET}.{TABLE}"

    table = bigquery.Table(table_id, schema=SCHEMA)
    # Lead volume is ~100-200/month org-wide, so partitioning is about pruning the incremental
    # lookback rather than cost. DAY on created_date matches how every consumer filters.
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="created_date")
    table.clustering_fields = ["project_name", "lead_source"]
    table.description = (
        "Geocon Salesforce LEADS via Windsor (connector salesforce__calvin@100.digital). "
        "One row per lead, MERGEd on lead_id so a status change updates in place. "
        "NO PII BY DESIGN - see create_salesforce_table.py. "
        "Loader: ingest/windsor_data_pull/salesforce/salesforce_loader.py "
        "(scheduled job windsor-salesforce-ingest). Consumer: client_geocon.stg_salesforce.")

    out = bq.create_table(table, exists_ok=True)
    print(f"ready: {out.full_table_id}")
    print(f"  partition: {out.time_partitioning.field if out.time_partitioning else None}")
    print(f"  cluster  : {out.clustering_fields}")
    print(f"  columns  : {len(out.schema)}")


if __name__ == "__main__":
    main()
