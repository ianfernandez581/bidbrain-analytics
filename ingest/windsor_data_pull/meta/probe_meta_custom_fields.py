r"""
Throwaway diagnostic v2 for the Windsor *Meta/Facebook* connector. Settles the
EXACT `fields=` token for the custom pixel conversion "Signup Button" on account
465058559225771.

KEY LESSON from v1: Windsor's /all does NOT 400 on an unknown field token -- it
silently drops it. So "HTTP 200" proves nothing; the real signals are:
  (1) KEY PRESENCE -- does the returned row actually CONTAIN the requested key?
      (present => Windsor recognises the token, even if its value is 0/null).
  (2) NON-ZERO data on that key.

This probe classifies every candidate by key-presence, and also asks for any
broad JSON-breakdown fields (actions / action_values / conversions / ...) that
might expose the per-conversion "Signup Button" line directly.

No BigQuery, no writes. Key via Secret Manager (ADC).
  .\.venv\Scripts\python.exe windsor_data_pull\meta\probe_meta_custom_fields.py
"""
import json
import requests
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"
WINDSOR_URL = "https://connectors.windsor.ai/all"
ACCOUNT = "facebook__465058559225771"
DATE_FROM = "2026-04-01"
DATE_TO = "2026-06-16"
CORE = "account_id,date,impressions,clicks,spend"

# Candidate tokens for the Signup Button custom conversion (count + value forms),
# plus broad breakdown fields that might carry it as JSON.
CANDIDATES = [
    "actions_offsite_conversion_fb_pixel_custom",          # v1: COUNT works (27 non-zero)
    "action_values_offsite_conversion_fb_pixel_custom",    # its value form
    "actions_offsite_conversion_custom",
    "action_values_offsite_conversion_custom",
    "actions_signup_button",
    "action_values_signup_button",
    "signup_button",
    "signup_button_conversion_value",
    "signup_button_value",
    "conversion_values_signup_button",
    "actions_offsite_conversion_fb_pixel_signup_button",
    "action_values_offsite_conversion_fb_pixel_signup_button",
]
BROAD = ["actions", "action_values", "conversions", "conversion_values",
         "custom_conversions", "offsite_conversion", "purchase_value"]


def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode("utf-8").strip()


def fetch(api_key, fields):
    params = {"api_key": api_key, "date_from": DATE_FROM, "date_to": DATE_TO,
              "fields": fields, "select_accounts": ACCOUNT}
    try:
        r = requests.get(WINDSOR_URL, params=params, timeout=180)
    except requests.exceptions.RequestException as e:
        return None, [], f"{type(e).__name__}: {e}"
    if r.status_code != 200:
        return r.status_code, [], r.text[:600]
    try:
        return r.status_code, r.json().get("data", []), ""
    except ValueError:
        return r.status_code, [], r.text[:600]


def classify(api_key, tok):
    """Probe core+tok alone. Returns (key_present, non_zero_count, sample)."""
    s, rows, body = fetch(api_key, CORE + "," + tok)
    if s != 200:
        return f"HTTP {s} body={body[:120]}"
    present = any(tok in r for r in rows)
    vals = [r.get(tok) for r in rows if r.get(tok) not in (None, "", "null")]
    nonzero = [v for v in vals if v not in (0, "0", 0.0)]
    return (f"key={'PRESENT' if present else 'ABSENT '}  "
            f"rows={len(rows)} nonnull={len(vals)} nonzero={len(nonzero)} "
            f"sample={nonzero[:4]}")


def main():
    api_key = get_secret("windsor-api-key")
    print("=" * 78)
    print(f"Windsor Meta custom-field probe v2  account={ACCOUNT}")
    print("=" * 78)

    print("\n-- CANDIDATE tokens (key-presence is the decisive signal) --")
    for tok in CANDIDATES:
        print(f"  {tok:<58} {classify(api_key, tok)}")

    print("\n-- BROAD breakdown fields (look for JSON exposing 'Signup Button') --")
    for tok in BROAD:
        s, rows, body = fetch(api_key, CORE + "," + tok)
        if s != 200:
            print(f"  {tok:<22} HTTP {s} body={body[:120]}")
            continue
        present = any(tok in r for r in rows)
        samples = [r.get(tok) for r in rows if r.get(tok) not in (None, "", "null")][:2]
        print(f"  {tok:<22} key={'PRESENT' if present else 'ABSENT'} sample={json.dumps(samples)[:300]}")

    print("\n" + "=" * 78)
    print("DONE.")
    print("=" * 78)


if __name__ == "__main__":
    main()
