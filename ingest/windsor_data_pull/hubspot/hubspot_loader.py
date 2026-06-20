"""
Windsor HUBSPOT loader -> raw_windsor.hubspot_contacts + raw_windsor.hubspot_deals.

Pulls Reset Data's HubSpot CRM (Windsor account 45274177, connector slug `hubspot`)
through the Windsor connectors API and snapshots it into BigQuery for the Reset Data
marketing dashboard (live contacts by lifecycle/owner/source, ROI by associated deal,
app-signup timeline, RdBillingBalance per contact, ad/source attribution).

WHY A SNAPSHOT (not the incremental MERGE the ad-platform loaders use): HubSpot here is
CRM CURRENT-STATE (one row per contact / per deal, no date grain). Each run pulls the
full object and WRITE_TRUNCATEs the table, so the table always equals "HubSpot right now".
4,700 contacts + 242 deals come back in a SINGLE request each (no pagination at this scale).

FIELDS: the exact Windsor field tokens were chosen by searching the per-ACCOUNT field
catalogue (https://connectors.windsor.ai/hubspot/fields, 2,144 fields incl. Reset Data's
custom contact_rd_* properties) across the dashboard's 6 data categories. The crown jewel
is contact_rd_billing_balance (= the client's "RdBillingBalance" custom property).

SCHEMA: every column is STRING (a faithful, lossless raw mirror that never fails to load);
typing is the dashboard view's job (the repo's "raw mirror, views type it" rule). A typed
convenience view is created alongside (see create_hubspot_views.sql / the dashboard SQL).

Key from Secret Manager (windsor-api-key) via ADC -- never inline it. Run:
    .\\.venv\\Scripts\\python.exe ingest\\windsor_data_pull\\hubspot\\hubspot_loader.py
"""
import json
import sys
import time

import requests
from google.cloud import bigquery, secretmanager

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
DATASET = "raw_windsor"
URL = "https://connectors.windsor.ai/hubspot"
CLIENT_SLUG = "resetdata"
AGENCY_SLUG = "100-digital"
# CRM is state, not a date series; cast a wide net so nothing is filtered out.
DATE_FROM, DATE_TO = "2015-01-01", "2026-12-31"

# --- exact Windsor field tokens, by object (bare aliases email/firstname/... dropped:
#     each has a contact_* canonical already listed) ---
CONTACT_FIELDS = [
    "contact_address", "contact_annualrevenue", "contact_city", "contact_closedate",
    "contact_company", "contact_company_size", "contact_country", "contact_createdate",
    "contact_currentlyinworkflow", "contact_days_to_close", "contact_email",
    "contact_engagements_last_meeting_booked", "contact_engagements_last_meeting_booked_campaign",
    "contact_engagements_last_meeting_booked_medium", "contact_engagements_last_meeting_booked_source",
    "contact_first_conversion_date", "contact_first_conversion_event_name",
    "contact_first_deal_created_date", "contact_firstname", "contact_hs_analytics_average_page_views",
    "contact_hs_analytics_first_referrer", "contact_hs_analytics_first_timestamp",
    "contact_hs_analytics_first_touch_converting_campaign", "contact_hs_analytics_first_url",
    "contact_hs_analytics_first_visit_timestamp", "contact_hs_analytics_last_referrer",
    "contact_hs_analytics_last_timestamp", "contact_hs_analytics_last_touch_converting_campaign",
    "contact_hs_analytics_last_url", "contact_hs_analytics_last_visit_timestamp",
    "contact_hs_analytics_num_event_completions", "contact_hs_analytics_num_page_views",
    "contact_hs_analytics_num_visits", "contact_hs_analytics_revenue", "contact_hs_analytics_source",
    "contact_hs_analytics_source_data_1", "contact_hs_analytics_source_data_2", "contact_hs_buying_role",
    "contact_hs_content_membership_registered_at", "contact_hs_content_membership_registration_email_sent_at",
    "contact_hs_createdate", "contact_hs_email_domain", "contact_hs_email_optout",
    "contact_hs_facebook_click_id", "contact_hs_google_click_id", "contact_hs_is_unworked",
    "contact_hs_last_sales_activity_timestamp", "contact_hs_lead_status",
    "contact_hs_lifecyclestage_customer_date", "contact_hs_lifecyclestage_evangelist_date",
    "contact_hs_lifecyclestage_lead_date", "contact_hs_lifecyclestage_marketingqualifiedlead_date",
    "contact_hs_lifecyclestage_opportunity_date", "contact_hs_lifecyclestage_other_date",
    "contact_hs_lifecyclestage_salesqualifiedlead_date", "contact_hs_lifecyclestage_subscriber_date",
    "contact_hs_marketable_status", "contact_hs_object_id", "contact_hs_persona",
    "contact_hs_predictivecontactscore", "contact_hs_predictivecontactscore_v2",
    "contact_hs_predictivecontactscorebucket", "contact_hs_predictivescoringtier",
    "contact_hs_sales_email_last_replied", "contact_hs_time_between_contact_creation_and_deal_close",
    "contact_hs_time_between_contact_creation_and_deal_creation",
    "contact_hs_time_to_move_from_lead_to_customer",
    "contact_hs_time_to_move_from_marketingqualifiedlead_to_customer",
    "contact_hs_time_to_move_from_opportunity_to_customer",
    "contact_hs_time_to_move_from_salesqualifiedlead_to_customer",
    "contact_hs_time_to_move_from_subscriber_to_customer", "contact_hs_v2_date_exited_customer",
    "contact_hs_v2_date_exited_evangelist", "contact_hs_v2_date_exited_lead",
    "contact_hs_v2_date_exited_opportunity", "contact_hs_v2_date_exited_other",
    "contact_hs_v2_date_exited_salesqualifiedlead", "contact_hs_v2_date_exited_subscriber",
    "contact_hs_v2_date_exitedmarketingqualifiedlead", "contact_hs_v2_latest_time_in_customer",
    "contact_hs_v2_latest_time_in_evangelist", "contact_hs_v2_latest_time_in_lead",
    "contact_hs_v2_latest_time_in_marketingqualifiedlead", "contact_hs_v2_latest_time_in_opportunity",
    "contact_hs_v2_latest_time_in_other", "contact_hs_v2_latest_time_in_salesqualifiedlead",
    "contact_hs_v2_latest_time_in_subscriber", "contact_hs_v2_total_time_in_customer",
    "contact_hs_v2_total_time_in_evangelist", "contact_hs_v2_total_time_in_lead",
    "contact_hs_v2_total_time_in_marketingqualifiedlead", "contact_hs_v2_total_time_in_opportunity",
    "contact_hs_v2_total_time_in_other", "contact_hs_v2_total_time_in_salesqualifiedlead",
    "contact_hs_v2_total_time_in_subscriber", "contact_hubspot_owner_assigneddate",
    "contact_hubspot_owner_id", "contact_hubspot_team_id", "contact_hubspotscore", "contact_industry",
    "contact_ip_city", "contact_ip_country", "contact_ip_state", "contact_job_function",
    "contact_jobtitle", "contact_lastmodifieddate", "contact_lastname", "contact_lifecyclestage",
    "contact_mobilephone", "contact_notes_last_contacted", "contact_notes_last_updated",
    "contact_notes_next_activity_date", "contact_num_associated_deals", "contact_num_contacted_notes",
    "contact_num_conversion_events", "contact_num_notes", "contact_num_unique_conversion_events",
    "contact_numemployees", "contact_phone", "contact_rd_billing_balance", "contact_rd_billing_mode",
    "contact_rd_business_name", "contact_rd_created_at", "contact_rd_email_verified",
    "contact_rd_has_payment_method", "contact_rd_is_active", "contact_rd_last_api_call",
    "contact_rd_last_login", "contact_rd_onboarded", "contact_rd_total_api_calls",
    "contact_rd_total_spend", "contact_rd_workspace_count", "contact_rd_workspace_role",
    "contact_recent_conversion_date", "contact_recent_conversion_event_name", "contact_recent_deal_amount",
    "contact_recent_deal_close_date", "contact_sales_status", "contact_salutation", "contact_seniority",
    "contact_source", "contact_state", "contact_total_revenue", "contact_type", "contact_website",
    "contact_work_email", "contact_zip",
]

DEAL_FIELDS = [
    "deal_amount", "deal_amount_in_home_currency", "deal_closed_lost_reason", "deal_closed_won_reason",
    "deal_closedate", "deal_count", "deal_createdate", "deal_currency_code", "deal_dealname",
    "deal_dealstage", "deal_dealtype", "deal_description", "deal_engagements_last_meeting_booked",
    "deal_engagements_last_meeting_booked_campaign", "deal_engagements_last_meeting_booked_medium",
    "deal_engagements_last_meeting_booked_source", "deal_hs_acv", "deal_hs_analytics_source",
    "deal_hs_analytics_source_data_1", "deal_hs_analytics_source_data_2", "deal_hs_arr",
    "deal_hs_forecast_amount", "deal_hs_forecast_probability", "deal_hs_lastmodifieddate",
    "deal_hs_manual_forecast_category", "deal_hs_mrr", "deal_hs_next_step", "deal_hs_object_id",
    "deal_hs_priority", "deal_hs_tcv", "deal_hubspot_owner_assigneddate", "deal_hubspot_owner_id",
    "deal_hubspot_team_id", "deal_notes_last_contacted", "deal_notes_last_updated",
    "deal_notes_next_activity_date", "deal_num_associated_contacts", "deal_num_contacted_notes",
    "deal_num_notes", "deal_pipeline",
]

# The HubSpot owner directory (~20 rows) — resolves contact/deal owner_id -> a name
# for the dashboard's "who owns this lead" / BDM-queue views.
OWNER_FIELDS = [
    "owner_owner_id", "owner_first_name", "owner_last_name", "owner_email",
    "owner_user_id", "owner_archived", "owner_created_at", "owner_updated_at",
]

EMPTY = {None, "", "null", "NULL", "(not set)"}


def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode("utf-8").strip()


def fetch(api_key, fields, retries=5):
    """GET the connector with capped-backoff retries; fail-fast on 4xx (bad field)."""
    backoff = 5
    params = {"api_key": api_key, "fields": ",".join(fields),
              "date_from": DATE_FROM, "date_to": DATE_TO}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(URL, params=params, timeout=300)
        except requests.exceptions.RequestException as e:
            if attempt == retries:
                raise
            print(f"  attempt {attempt} failed ({type(e).__name__}); retry in {backoff}s")
            time.sleep(backoff); backoff = min(backoff * 2, 120); continue
        if r.status_code == 200:
            return r.json().get("data", [])
        if 400 <= r.status_code < 500 and r.status_code != 429:
            raise RuntimeError(f"Windsor /hubspot HTTP {r.status_code}: {r.text[:600]}")
        if attempt == retries:
            raise RuntimeError(f"Windsor /hubspot HTTP {r.status_code} after {retries}: {r.text[:400]}")
        print(f"  HTTP {r.status_code} attempt {attempt}; retry in {backoff}s")
        time.sleep(backoff); backoff = min(backoff * 2, 120)


def to_string_row(raw, fields, now_iso):
    """Lossless STRING row: empty-ish -> None, everything else -> str(); + metadata."""
    out = {}
    for f in fields:
        v = raw.get(f)
        out[f] = None if (v in EMPTY or (isinstance(v, str) and v.strip() in EMPTY)) else str(v)
    out["account_id"] = str(raw.get("account_id") or "")
    out["client_slug"] = CLIENT_SLUG
    out["agency_slug"] = AGENCY_SLUG
    out["_pulled_at"] = now_iso
    out["raw_row"] = json.dumps(raw, ensure_ascii=False)
    return out


def load(bq, table, fields, rows):
    schema = ([bigquery.SchemaField(f, "STRING") for f in fields] +
              [bigquery.SchemaField("account_id", "STRING"),
               bigquery.SchemaField("client_slug", "STRING"),
               bigquery.SchemaField("agency_slug", "STRING"),
               bigquery.SchemaField("_pulled_at", "TIMESTAMP"),
               bigquery.SchemaField("raw_row", "JSON")])
    table_id = f"{PROJECT}.{DATASET}.{table}"
    cfg = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    bq.load_table_from_json(rows, table_id, job_config=cfg).result()
    n = list(bq.query(f"SELECT COUNT(*) c FROM `{table_id}`").result())[0].c
    print(f"  loaded {table_id}: {n} rows, {len(schema)} columns")


def main():
    print("=" * 70)
    print("Windsor HubSpot loader -> raw_windsor.hubspot_contacts + hubspot_deals")
    print("=" * 70)
    api_key = get_secret("windsor-api-key")
    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    now_iso = list(bq.query("SELECT CAST(CURRENT_TIMESTAMP() AS STRING) t").result())[0].t

    print(f"\nCONTACTS: requesting {len(CONTACT_FIELDS)} fields ...")
    contacts = fetch(api_key, CONTACT_FIELDS)
    print(f"  fetched {len(contacts)} contacts")
    if not contacts:
        print("  no contacts returned -- aborting"); sys.exit(1)
    load(bq, "hubspot_contacts", CONTACT_FIELDS,
         [to_string_row(r, CONTACT_FIELDS, now_iso) for r in contacts])

    print(f"\nDEALS: requesting {len(DEAL_FIELDS)} fields ...")
    deals = fetch(api_key, DEAL_FIELDS)
    print(f"  fetched {len(deals)} deals")
    load(bq, "hubspot_deals", DEAL_FIELDS,
         [to_string_row(r, DEAL_FIELDS, now_iso) for r in deals])

    print(f"\nOWNERS: requesting {len(OWNER_FIELDS)} fields ...")
    owners = fetch(api_key, OWNER_FIELDS)
    print(f"  fetched {len(owners)} owners")
    if owners:
        load(bq, "hubspot_owners", OWNER_FIELDS,
             [to_string_row(r, OWNER_FIELDS, now_iso) for r in owners])

    print("\nDONE.")


if __name__ == "__main__":
    main()
