# probe_google_ads_fields.py
"""
Throwaway diagnostic for the Windsor *Google Ads* connector -- the sibling of
probe_ga4_fields.py. Run ONCE, before building the table/loader, to settle three
questions empirically (Windsor's field reference lists fields that come back NULL,
and the account-selection format differs per connector):

  1. ACCOUNT-SELECTION FORMAT. Does the dedicated /google_ads endpoint want the
     BARE customer id (`105-440-7474`, like the GA4 endpoint) or the PREFIXED form
     (`google_ads__105-440-7474`, like the blended /all endpoint)? -> tests BOTH
     against the first account and prints HTTP status + row count for each.
  2. STORED account_id FORMAT. Exactly what string does Windsor put in `account_id`
     -- hyphenated `105-440-7474` or bare `1054407474`? This decides the stored
     customer_id format and the MERGE-key normalisation.
  3. WHICH REQUESTED FIELDS ACTUALLY POPULATE. Prints a populated-vs-all-NULL
     summary per field. campaign_type and currency_code are the names most likely
     to come back NULL -- watch those.

Not part of the normal run. Mirrors the GA4 probe; no BigQuery, no writes.

Run:  .\\.venv\\Scripts\\python.exe windsor_data_pull\\google_ads\\probe_google_ads_fields.py
"""
import requests
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"
WINDSOR_URL = "https://connectors.windsor.ai/google_ads"

# The agreed probe field set: additive base only, one cost field (spend), no ratios.
FIELDS = ("date,account_id,account_name,campaign_id,campaign,campaign_type,"
          "currency_code,impressions,clicks,spend,conversions,conversions_value")
FIELD_LIST = FIELDS.split(",")

# Recent ~14-day window.
DATE_FROM = "2026-05-15"
DATE_TO = "2026-05-30"

# The four accounts as received (note the google_ads__ prefix in the raw handles;
# the probe validates whether the dedicated endpoint wants it or not).
RAW_ACCOUNTS = [
    "105-440-7474",
    "261-791-6504",
    "519-659-6415",
    "850-931-3407",
]

# Values that are present-but-empty -- treated as NOT populated in the summary.
EMPTY_VALUES = {None, "", "null", "(not set)", "(not_set)"}


def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode("utf-8").strip()


def fetch(api_key, select_accounts):
    """Return (status_code, rows, body_snippet). Never raises on HTTP error so we
    can SEE the error body (that's how the GA4 field-name gotcha was found)."""
    params = {
        "api_key": api_key,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "fields": FIELDS,
        "select_accounts": select_accounts,
    }
    r = requests.get(WINDSOR_URL, params=params, timeout=120)
    if r.status_code != 200:
        return r.status_code, [], r.text[:800]
    try:
        payload = r.json()
    except ValueError:
        return r.status_code, [], r.text[:800]
    return r.status_code, payload.get("data", []), ""


def is_populated(v):
    if isinstance(v, str):
        return v.strip().lower() not in {e for e in EMPTY_VALUES if isinstance(e, str)}
    return v not in EMPTY_VALUES


def null_summary(rows):
    """populated count per requested field across `rows`."""
    n = len(rows)
    print(f"\n  populated-vs-NULL summary over {n} rows:")
    for f in FIELD_LIST:
        pop = sum(1 for row in rows if is_populated(row.get(f)))
        flag = ""
        if pop == 0:
            flag = "   <<< ALL NULL"
        elif pop < n:
            flag = f"   (partial: {n - pop} empty)"
        print(f"    {f:<20} {pop}/{n} populated{flag}")


def main():
    print("=" * 70)
    print("Windsor Google Ads connector probe")
    print(f"  endpoint : {WINDSOR_URL}")
    print(f"  window   : {DATE_FROM} .. {DATE_TO}")
    print(f"  fields   : {FIELDS}")
    print("=" * 70)

    api_key = get_secret("windsor-api-key")
    print(f"got windsor-api-key (length {len(api_key)})\n")

    # ---- PHASE 1: account-selection format (test BOTH on the first account) ----
    first = RAW_ACCOUNTS[0]
    print("-" * 70)
    print(f"PHASE 1 -- account-format test on first account ({first})")
    print("-" * 70)

    status_a, rows_a, body_a = fetch(api_key, first)                       # bare
    print(f"  (a) bare      select_accounts={first!r:>22}  -> HTTP {status_a}, {len(rows_a)} rows")
    if body_a:
        print(f"       body: {body_a}")

    prefixed = f"google_ads__{first}"
    status_b, rows_b, body_b = fetch(api_key, prefixed)                    # prefixed
    print(f"  (b) prefixed  select_accounts={prefixed!r}  -> HTTP {status_b}, {len(rows_b)} rows")
    if body_b:
        print(f"       body: {body_b}")

    if len(rows_a) > 0:
        winning_prefix, winner = "", "(a) bare"
    elif len(rows_b) > 0:
        winning_prefix, winner = "google_ads__", "(b) prefixed"
    else:
        winning_prefix, winner = "", "(neither returned rows -- defaulting to bare for Phase 2)"
    print(f"\n  => winning format: {winner}   (ACCOUNT_PREFIX = {winning_prefix!r})")

    # ---- PHASE 2: all four accounts together, in the winning format ----
    combined = ",".join(f"{winning_prefix}{a}" for a in RAW_ACCOUNTS)
    print("\n" + "-" * 70)
    print(f"PHASE 2 -- all four accounts together (format: {winner})")
    print(f"  select_accounts={combined}")
    print("-" * 70)

    status, rows, body = fetch(api_key, combined)
    print(f"  HTTP {status}, {len(rows)} rows total")
    if body:
        print(f"  body: {body}")
    if not rows:
        print("\n  No rows -- cannot profile fields/accounts. Stopping.")
        return

    # Distinct account_id values Windsor returns (answers the hyphen-vs-bare question).
    distinct_ids = sorted({str(r.get("account_id")) for r in rows})
    print(f"\n  distinct account_id values returned ({len(distinct_ids)}):")
    for aid in distinct_ids:
        name = next((r.get("account_name") for r in rows if str(r.get("account_id")) == aid), None)
        cnt = sum(1 for r in rows if str(r.get("account_id")) == aid)
        print(f"    account_id={aid!r:>16}  account_name={name!r:<40}  rows={cnt}")

    # Which requested accounts returned NOTHING.
    returned_digits = {''.join(ch for ch in i if ch.isdigit()) for i in distinct_ids}
    missing = [a for a in RAW_ACCOUNTS if ''.join(ch for ch in a if ch.isdigit()) not in returned_digits]
    if missing:
        print(f"\n  !! requested accounts with NO rows: {missing}")

    # All keys Windsor actually returns (may differ from requested names).
    all_keys = sorted({k for r in rows for k in r.keys()})
    print(f"\n  all keys present in returned rows ({len(all_keys)}): {all_keys}")

    # Populated-vs-NULL per requested field.
    null_summary(rows)

    # 10-15 sample raw rows.
    print(f"\n  first {min(15, len(rows))} raw rows:")
    for row in rows[:15]:
        print(f"    {row}")

    print("\n" + "=" * 70)
    print("PROBE DONE. Report back: (1) winning account format, (2) exact account_id "
          "format, (3) any ALL-NULL field (esp. campaign_type / currency_code).")
    print("=" * 70)


if __name__ == "__main__":
    main()
