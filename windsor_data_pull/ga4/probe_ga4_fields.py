# probe_ga4_fields.py
import requests
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"
def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode().strip()

fields = ("account_id,date,source,medium,session_source_medium,"
          "campaign,campaign_name,session_campaign_id,"
          "session_default_channel_group,sessions")
r = requests.get("https://connectors.windsor.ai/googleanalytics4", params={
    "api_key": get_secret("windsor-api-key"),
    # in probe_ga4_fields.py:
"date_from": "2026-05-17", "date_to": "2026-05-30",
    "fields": fields,
    "select_accounts": "318963196",   # STT GDC Web All — rich paid+organic mix
}, timeout=120)
r.raise_for_status()
rows = r.json().get("data", [])
print(f"{len(rows)} rows\n")
for row in rows[:15]:
    print(row)