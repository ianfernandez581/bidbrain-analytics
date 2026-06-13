# windsor_data_pull/ga4/probe_ga4_event_fields.py
#
# Throwaway diagnostic (same role as probe_ga4_fields.py): confirm what Windsor's
# googleanalytics4 connector ACTUALLY returns for the EVENT-scoped fields before
# building perf_ga4_events. Verify the names populate, and SEE the grain change
# (one row per event_name) firsthand.
import requests
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"

def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode().strip()

# Event grain: date x event_name (+ is_conversion_event), with the additive
# event metrics. event_value = SUM of the 'value' event param; conversions = key events.
fields = ("account_id,date,"
          "event_name,is_conversion_event,"
          "event_count,event_value,conversions")

r = requests.get("https://connectors.windsor.ai/googleanalytics4", params={
    "api_key": get_secret("windsor-api-key"),
    "date_from": "2026-05-24", "date_to": "2026-05-30",
    "fields": fields,
    "select_accounts": "318963196",   # STT GDC Web All — rich event mix
}, timeout=120)
r.raise_for_status()
rows = r.json().get("data", [])
print(f"{len(rows)} rows for: {fields}\n")

# Distinct event names confirm the grain + that event_name actually populates.
names = {}
for row in rows:
    names[row.get("event_name")] = names.get(row.get("event_name"), 0) + 1
print("distinct event_name (None == Windsor NOT populating it):")
for n, c in sorted(names.items(), key=lambda kv: -kv[1]):
    print(f"  {str(n)!r:35} {c} rows")

print("\nfirst 15 raw rows:")
for row in rows[:15]:
    print(row)