"""
Throwaway diagnostic for the Windsor *LinkedIn Ads* connector -- the sibling of
probe_reddit_fields.py. Run ONCE, before building the table/loader, to settle empirically
the questions Windsor's field reference can't (it lists fields that come back NULL, /all
silently nulls some platform-native dims, and LinkedIn's API adds its own limits).

LinkedIn is requested through the BLENDED /all endpoint with a `linkedin__` account prefix
(same mechanics as meta_loader / reddit_loader), NOT a dedicated /linkedin connector (that
also works but /all is the house pattern). Key read from Secret Manager via ADC -- NEVER
inlined, NEVER passed on argv.

THE FINDINGS THIS PROBE SETTLED (2026-07-21, all confirmed against the live connector):

  1. GRAIN. campaign_group_id is ALL NULL on /all, but campaign_id (100% populated) and
     creative_id (100% populated) both populate -> GRAIN = creative-level by id
     (_MERGE_KEY_COLS = account_id, creative_id, metric_date). Exactly one row per
     (account, campaign, creative, date) cell (max=1 verified). campaign / campaign_group_name
     ride along as attributes. => store campaign_group_NAME, OMIT campaign_group_id.

  2. 20-FIELD CAP. LinkedIn's adAnalytics API rejects any request with >20 fields
     ("LinkedIn allows at most 20 fields per adAnalytics request"). => the loader fetches
     each chunk in TWO <=20-field passes and merges them on (account_id, creative_id, date).

  3. 92-DAY REACH CAP. `approximate_unique_impressions` (reach) is only available for windows
     <= 92 days ("... are only available for up to 92 days"). => CHUNK_DAYS=30 stays under it.

  4. PER-ACCOUNT FETCH IS MANDATORY. /all fails the WHOLE multi-account request if ONE account
     errors, so the loader fetches ONE account per request. Two failure shapes seen:
       * account 502299829 -> HTTP 500 "'start'" for EVERY window/field combo (a Windsor bug:
         a campaign missing a start date breaks its adAnalytics pull). PERMANENT -> skip the
         account (AccountUnavailableError), like a 400 "not available".
       * a big account over a 90-day window -> HTTP 500 "Response ended prematurely" (size).
         TRANSIENT -> retry; small CHUNK_DAYS avoids it.

  5. CURRENCY. `currency` populates 100% and is the account's NATIVE spend currency (AUD, SGD
     and USD all seen across the connected accounts) -- NOT USD. => store it for FX.

  6. FIELD NAMES. `campaign` IS the campaign name (there is no separate campaign_name field).
     Lead-gen: `oneclickleads` (Lead Gen Form submissions) + `oneclickleadformopens`. Site
     conversions: `externalwebsiteconversions` (+ post-click/post-view split). Video quartiles
     are `quartile_1/2/3`. All populated on the accounts with delivery.

Not part of the normal run. No BigQuery, no writes.

Run:  .\\.venv\\Scripts\\python.exe windsor_data_pull\\linkedin\\probe_linkedin_fields.py [date_from date_to]
      (defaults to a recent <=90-day window so the reach field stays inside its 92-day cap)
"""
import sys
import requests
from collections import defaultdict
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"
WINDSOR_URL = "https://connectors.windsor.ai/all"
ACCOUNT_PREFIX = "linkedin__"

# The full account set granted on the 2026-07 connector.
ACCOUNTS = [
    "502299829", "504047196", "504606769", "504758918", "507224127", "507877947",
    "508673116", "508732444", "508766215", "508768204", "508768205", "508801607",
    "509003962", "509046900", "509091286", "509841591", "510177932", "510202977",
    "511313581", "511609128", "512344932", "512350710", "512810387", "513554482",
    "515691430", "516221072", "516746102", "516748074", "517045062", "517047078",
    "520254094", "547920275", "547920277", "547960230",
]

# <=20 fields (the LinkedIn cap). Enumeration + hierarchy + currency probe.
FIELDS = (
    "account_id,account_name,currency,"
    "campaign_group_name,campaign_id,campaign,creative_id,"
    "objective_type,campaign_type,date,"
    "impressions,clicks,spend,approximate_unique_impressions,landingpageclicks,"
    "oneclickleads,oneclickleadformopens,externalwebsiteconversions"
)

DATE_FROM = sys.argv[1] if len(sys.argv) > 2 else "2026-04-22"
DATE_TO   = sys.argv[2] if len(sys.argv) > 2 else "2026-07-21"

EMPTY = {None, "", "null", "(not set)", "(not_set)"}


def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode("utf-8").strip()


API_KEY = get_secret("windsor-api-key")


def fetch(accounts):
    params = {
        "api_key": API_KEY, "date_from": DATE_FROM, "date_to": DATE_TO,
        "fields": FIELDS,
        "select_accounts": ",".join(f"{ACCOUNT_PREFIX}{a}" for a in accounts),
    }
    try:
        r = requests.get(WINDSOR_URL, params=params, timeout=300)
    except requests.exceptions.RequestException as e:
        return None, [], f"{type(e).__name__}: {e}"
    if r.status_code != 200:
        return r.status_code, [], r.text[:400]
    return 200, r.json().get("data", []), ""


def is_pop(v):
    if isinstance(v, str):
        return v.strip().lower() not in {e for e in EMPTY if isinstance(e, str)}
    return v not in EMPTY


def main():
    print("=" * 80)
    print(f"Windsor LinkedIn /all probe  window {DATE_FROM}..{DATE_TO}  accounts={len(ACCOUNTS)} (per-account)")
    print("=" * 80)
    rows, fails = [], {}
    for a in ACCOUNTS:
        s, rr, body = fetch([a])
        if s == 200:
            rows += rr
            if rr:
                print(f"  {a}: {len(rr)} rows")
        else:
            fails[a] = f"HTTP {s}: {body[:120]}"
            print(f"  {a}: FAIL {fails[a]}")
    print(f"\nTOTAL rows={len(rows)}  failed_accounts={len(fails)}")
    if not rows:
        return

    n = len(rows)
    print("\npopulated-vs-null:")
    for f in FIELDS.split(","):
        p = sum(1 for r in rows if is_pop(r.get(f)))
        flag = "  <<< ALL NULL" if p == 0 else (f"  (partial {n-p} empty)" if p < n else "")
        print(f"  {f:34} {p}/{n}{flag}")

    print("\nHIERARCHY populate (decides the grain):")
    for f in ("campaign_group_id", "campaign_id", "creative_id"):
        p = sum(1 for r in rows if is_pop(r.get(f)))
        d = len({str(r.get(f)) for r in rows if is_pop(r.get(f))})
        print(f"  {f:20} {p}/{n} populated, {d} distinct")

    grain = defaultdict(int)
    for r in rows:
        grain[(r.get("account_id"), r.get("campaign_id"), r.get("creative_id"), r.get("date"))] += 1
    print(f"\nrows per (account,campaign,creative,date): max={max(grain.values())} (1 => creative is finest grain)")
    print(f"currency values: {sorted({str(r.get('currency')) for r in rows if is_pop(r.get('currency'))})}")

    acc = defaultdict(lambda: [None, 0.0, set()])
    for r in rows:
        a = str(r.get("account_id"))
        acc[a][0] = r.get("account_name")
        try: acc[a][1] += float(r.get("spend") or 0)
        except (TypeError, ValueError): pass
        if is_pop(r.get("campaign")): acc[a][2].add(r.get("campaign"))
    print(f"\n{len(acc)} accounts returning data:")
    for a in sorted(acc, key=lambda x: -acc[x][1]):
        nm, sp, camps = acc[a]
        print(f"  {a:12} {str(nm)[:44]:44} spend={sp:12.2f} campaigns={len(camps)}")

    print("\nMONGODB campaigns (campaign name contains 'mongo'):")
    hit = sorted({r.get("campaign") for r in rows if "mongo" in str(r.get("campaign")).lower()})
    print("  " + ("\n  ".join(hit) if hit else "NONE FOUND in this window/accounts"))


if __name__ == "__main__":
    main()
