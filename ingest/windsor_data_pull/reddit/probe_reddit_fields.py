# probe_reddit_fields.py
"""
Throwaway diagnostic for the Windsor *Reddit Ads* connector -- the sibling of
probe_google_ads_fields.py / probe_ga4_fields.py. Run ONCE, before building the
table/loader, to settle empirically the questions Windsor's field reference can't
(it lists fields that come back NULL, and /all silently nulls some platform-native
dims -- that's the GA4 lesson we are NOT going to relearn the hard way).

Reddit is requested through the BLENDED /all endpoint with a `reddit__` account
prefix (same mechanics as meta_loader.py), NOT a dedicated /reddit connector.

PHASES (one probe run settles everything):

  PHASE 1 -- CORE SANITY. Hit /all with a tiny, certainly-valid field set
     (account_id, account_name, campaign, date, impressions, clicks, spend) so we
     can tell "the endpoint + account + key actually work" apart from "one of my
     curated field NAMES is wrong" (a bad name 400s the WHOLE request). Also
     captures the exact account_id STRING Windsor returns -> finding #2.

  PHASE 2 -- FULL CURATED SET + NULL AUDIT. The real probe: send the agreed
     additive-base field set and print populated-vs-NULL per field, the hierarchy-ID
     verdict (the central question -> finding #1), distinct id counts,
     rows-per-(account_id, date), currency, and a percent-scale sanity peek.

  PHASE 3 -- ESCALATION (only if /all NULLs the hierarchy IDs). Re-probes the
     dedicated https://connectors.windsor.ai/reddit connector (bare account id, the
     google_ads finding) for the SAME ids, so we know before building whether to use
     (a) /all by-id, (b) the dedicated connector by-id, or (c) a name-based grain.

THE FIVE FINDINGS TO REPORT (see the prompt's Definition of Done):
  1. Do campaign_id / ad_group_id / ad_id populate?  -> decides the GRAIN.
  2. Exact account_id string Windsor returns (bare a2_... vs prefixed reddit__a2_...).
  3. NULL audit on the rest -- esp. account_currency, campaign_objective, the
     conversion click/view split fields, and campaign_name vs campaign.
  4. Spend currency: USD or the account's native currency? (account_currency).
  5. PERCENT-scale sanity on anything numeric we store (mostly N/A -- counts).

Not part of the normal run. No BigQuery, no writes. The api key is read from Secret
Manager via ADC -- NEVER inline it, NEVER pass it on argv.

Run:  .\\.venv\\Scripts\\python.exe windsor_data_pull\\reddit\\probe_reddit_fields.py
"""
import requests
from google.cloud import secretmanager

PROJECT_ID = "bidbrain-analytics"
WINDSOR_URL_ALL = "https://connectors.windsor.ai/all"        # blended endpoint (reddit__ prefix)
WINDSOR_URL_REDDIT = "https://connectors.windsor.ai/reddit"  # dedicated endpoint (Phase-3 fallback only)

# One confirmed-live Reddit account. ALPHANUMERIC -- this is the landmine: the
# siblings' re.sub(r"\D","",...) account_key would collapse it to "2". Probe with
# the reddit__ prefix on /all (Meta-style), bare on the dedicated /reddit endpoint.
RAW_ACCOUNT = "a2_igd0szmw7roq"
ACCOUNT_PREFIX = "reddit__"

# Recent ~14-day window (today 2026-06-12).
DATE_FROM = "2026-05-29"
DATE_TO = "2026-06-11"

# Phase 1: minimal, certainly-valid fields -- isolates "works at all" from a bad field name.
CORE_FIELDS = "account_id,account_name,campaign,date,impressions,clicks,spend"

# Phase 2: the agreed curated set (additive base only, one cost field, no ratios).
# NOTE: `campaign` is added ALONGSIDE `campaign_name` purely to settle finding #3's
# "campaign_name vs campaign -- which populates?" -- the loader keeps only one.
FULL_FIELDS = (
    "account_id,account_name,account_currency,"
    "campaign_id,campaign,campaign_name,campaign_objective,"
    "ad_group_id,ad_group_name,ad_id,ad_name,date,datasource,"
    "impressions,clicks,spend,reach,"
    "upvotes,downvotes,comment_submissions,"
    "video_started,video_watched_25_percent,video_watched_50_percent,"
    "video_watched_75_percent,video_watched_100_percent,"
    "conversion_lead_clicks,conversion_lead_views,"
    "conversion_sign_up_clicks,conversion_sign_up_views,"
    "conversion_page_visit_clicks,conversion_page_visit_views,"
    "lead_total_value,signup_total_value"
)

# Hierarchy ids -- the central question. If these come back NULL on /all we escalate.
HIERARCHY_IDS = ["campaign_id", "ad_group_id", "ad_id"]

# Values that are present-but-empty -- treated as NOT populated in the summary.
EMPTY_VALUES = {None, "", "null", "(not set)", "(not_set)"}


def get_secret(name):
    c = secretmanager.SecretManagerServiceClient()
    p = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
    return c.access_secret_version(name=p).payload.data.decode("utf-8").strip()


def fetch(url, api_key, select_accounts, fields):
    """Return (status_code, rows, body_snippet). Never raises on HTTP error so we can
    SEE the error body (that is how the GA4 bad-field-name gotcha was found)."""
    params = {
        "api_key": api_key,
        "date_from": DATE_FROM,
        "date_to": DATE_TO,
        "fields": fields,
        "select_accounts": select_accounts,
    }
    try:
        r = requests.get(url, params=params, timeout=180)
    except requests.exceptions.RequestException as e:
        return None, [], f"{type(e).__name__}: {e}"
    if r.status_code != 200:
        return r.status_code, [], r.text[:1000]
    try:
        payload = r.json()
    except ValueError:
        return r.status_code, [], r.text[:1000]
    return r.status_code, payload.get("data", []), ""


def is_populated(v):
    if isinstance(v, str):
        return v.strip().lower() not in {e for e in EMPTY_VALUES if isinstance(e, str)}
    return v not in EMPTY_VALUES


def null_summary(rows, field_list):
    """Populated count per requested field across `rows`."""
    n = len(rows)
    print(f"\n  populated-vs-NULL summary over {n} rows:")
    for f in field_list:
        pop = sum(1 for row in rows if is_populated(row.get(f)))
        flag = ""
        if pop == 0:
            flag = "   <<< ALL NULL"
        elif pop < n:
            flag = f"   (partial: {n - pop} empty)"
        print(f"    {f:<28} {pop}/{n} populated{flag}")


def distinct_nonempty(rows, field):
    return sorted({str(r.get(field)) for r in rows if is_populated(r.get(field))})


def hierarchy_verdict(rows):
    """The central question: do the Reddit hierarchy ids populate, or does /all null
    them (the GA4 pattern)? Prints populated count + distinct count per id field."""
    n = len(rows)
    print("\n  >>> HIERARCHY-ID VERDICT (finding #1 -- decides the grain):")
    populated_flags = {}
    for f in HIERARCHY_IDS:
        pop = sum(1 for r in rows if is_populated(r.get(f)))
        distinct = len(distinct_nonempty(rows, f))
        populated_flags[f] = pop > 0
        verdict = "POPULATED" if pop > 0 else "ALL NULL"
        print(f"    {f:<14} {pop}/{n} populated, {distinct} distinct  -> {verdict}")
    if all(populated_flags.values()):
        print("    => /all returns the Reddit hierarchy ids. GRAIN = ad-level by id "
              "(_MERGE_KEY_COLS = account_id, ad_id, metric_date).")
    else:
        nulled = [f for f, ok in populated_flags.items() if not ok]
        print(f"    => /all NULLs {nulled} (the GA4 pattern). Escalating in Phase 3: "
              "try dedicated /reddit; else fall back to a NAME-based grain.")
    return all(populated_flags.values())


def rows_per_account_date(rows):
    """Rows per (account_id, date). >1 on average means a true sub-account grain
    (ad / ad-group / campaign) rather than one collapsed daily row per account."""
    counts = {}
    for r in rows:
        k = (str(r.get("account_id")), str(r.get("date")))
        counts[k] = counts.get(k, 0) + 1
    if not counts:
        return
    vals = sorted(counts.values())
    print(f"\n  rows per (account_id, date): "
          f"min={vals[0]} max={vals[-1]} avg={sum(vals)/len(vals):.1f} "
          f"over {len(counts)} (account,date) cells")
    for k, c in list(sorted(counts.items()))[:8]:
        print(f"    {k} -> {c} rows")


def numeric_peek(rows, field_list):
    """Min/max of every numeric-looking field -- the percent-scale (0-1 vs 0-100)
    sanity check (finding #5; mostly N/A since we store counts)."""
    print("\n  numeric min/max peek (percent-scale sanity; counts should look like counts):")
    for f in field_list:
        nums = []
        for r in rows:
            v = r.get(f)
            if v in EMPTY_VALUES:
                continue
            try:
                nums.append(float(v))
            except (TypeError, ValueError):
                pass
        if nums:
            print(f"    {f:<28} min={min(nums):<12g} max={max(nums):<12g} n={len(nums)}")


def profile(rows, field_list, *, full):
    # Exact account_id string Windsor returns (finding #2).
    acct_ids = distinct_nonempty(rows, "account_id")
    print(f"\n  distinct account_id values returned ({len(acct_ids)}): {acct_ids}")
    print("    (finding #2: confirm bare 'a2_igd0szmw7roq' vs prefixed 'reddit__a2_...')")

    # All keys Windsor actually returns (may differ from requested names).
    all_keys = sorted({k for r in rows for k in r.keys()})
    print(f"\n  all keys present in returned rows ({len(all_keys)}): {all_keys}")

    if full:
        ids_ok = hierarchy_verdict(rows)
        rows_per_account_date(rows)
        # account_currency -> finding #4.
        cur = distinct_nonempty(rows, "account_currency")
        print(f"\n  account_currency values (finding #4 -- FX): {cur or '<<< ALL NULL>>>'}")
        # campaign vs campaign_name -> finding #3.
        camp = sum(1 for r in rows if is_populated(r.get("campaign")))
        campn = sum(1 for r in rows if is_populated(r.get("campaign_name")))
        print(f"  campaign vs campaign_name (finding #3): "
              f"campaign={camp}/{len(rows)} populated, campaign_name={campn}/{len(rows)} populated")
        # datasource sanity -- rows should be 'reddit'.
        ds = distinct_nonempty(rows, "datasource")
        print(f"  datasource values (should be reddit): {ds}")
    else:
        ids_ok = None

    null_summary(rows, field_list)
    if full:
        numeric_peek(rows, [
            "impressions", "clicks", "spend", "reach", "upvotes", "downvotes",
            "comment_submissions", "video_started", "video_watched_100_percent",
            "conversion_lead_clicks", "conversion_lead_views",
            "conversion_sign_up_clicks", "conversion_sign_up_views",
            "conversion_page_visit_clicks", "conversion_page_visit_views",
            "lead_total_value", "signup_total_value",
        ])

    print(f"\n  first {min(10, len(rows))} raw rows:")
    for row in rows[:10]:
        print(f"    {row}")
    return ids_ok


def main():
    print("=" * 74)
    print("Windsor Reddit Ads connector probe (blended /all)")
    print(f"  endpoint : {WINDSOR_URL_ALL}")
    print(f"  account  : {ACCOUNT_PREFIX}{RAW_ACCOUNT}")
    print(f"  window   : {DATE_FROM} .. {DATE_TO}")
    print("=" * 74)

    api_key = get_secret("windsor-api-key")
    print(f"got windsor-api-key (length {len(api_key)})\n")

    prefixed = f"{ACCOUNT_PREFIX}{RAW_ACCOUNT}"

    # ---- PHASE 1: core sanity (tiny safe field set) ----
    print("-" * 74)
    print("PHASE 1 -- core sanity (minimal field set; isolates a bad field name)")
    print(f"  select_accounts={prefixed!r}  fields={CORE_FIELDS}")
    print("-" * 74)
    s1, rows1, body1 = fetch(WINDSOR_URL_ALL, api_key, prefixed, CORE_FIELDS)
    print(f"  HTTP {s1}, {len(rows1)} rows")
    if body1:
        print(f"  body/error: {body1}")
    if rows1:
        profile(rows1, CORE_FIELDS.split(","), full=False)
    if not rows1:
        print("\n  !! PHASE 1 returned no rows. Either the account has no spend in this "
              "window, the reddit__ prefix is wrong, or access isn't granted. "
              "Check the body above before continuing.")

    # ---- PHASE 2: full curated set + NULL audit ----
    print("\n" + "-" * 74)
    print("PHASE 2 -- full curated field set + NULL audit")
    print(f"  select_accounts={prefixed!r}")
    print(f"  fields={FULL_FIELDS}")
    print("-" * 74)
    s2, rows2, body2 = fetch(WINDSOR_URL_ALL, api_key, prefixed, FULL_FIELDS)
    print(f"  HTTP {s2}, {len(rows2)} rows")
    if body2:
        print(f"  body/error: {body2}")
        print("  (if HTTP 400: one curated field NAME is likely invalid -- the body "
              "usually names it. Phase 1 still proves the endpoint/account work.)")

    ids_ok = None
    if rows2:
        ids_ok = profile(rows2, FULL_FIELDS.split(","), full=True)

    # ---- PHASE 3: escalate to the dedicated /reddit connector iff /all nulled the ids ----
    if rows2 and ids_ok is False:
        print("\n" + "-" * 74)
        print("PHASE 3 -- /all NULLed the hierarchy ids; testing dedicated /reddit connector")
        print(f"  endpoint={WINDSOR_URL_REDDIT}  select_accounts={RAW_ACCOUNT!r} (bare)")
        print("-" * 74)
        # Dedicated connectors take the BARE id (the google_ads finding). Try bare first,
        # then prefixed as a backstop.
        s3, rows3, body3 = fetch(WINDSOR_URL_REDDIT, api_key, RAW_ACCOUNT, FULL_FIELDS)
        print(f"  (bare)     HTTP {s3}, {len(rows3)} rows")
        if body3:
            print(f"    body/error: {body3}")
        if not rows3:
            s3b, rows3, body3b = fetch(WINDSOR_URL_REDDIT, api_key, prefixed, FULL_FIELDS)
            print(f"  (prefixed) HTTP {s3b}, {len(rows3)} rows")
            if body3b:
                print(f"    body/error: {body3b}")
        if rows3:
            print("\n  dedicated /reddit connector returned rows -- re-running hierarchy verdict:")
            hierarchy_verdict(rows3)
            print("  => if ids POPULATE here, build via the dedicated /reddit connector by-id.")
        else:
            print("\n  => dedicated /reddit also unavailable/empty. FALL BACK to a NAME-based "
                  "grain: account_id x campaign_name x ad_group_name x ad_name x metric_date, "
                  "all coalesced to '(not set)'. Document as a known limitation.")

    print("\n" + "=" * 74)
    print("PROBE DONE. Report the five findings (see module docstring), then decide the "
          "grain from finding #1 BEFORE building the table/loader.")
    print("=" * 74)


if __name__ == "__main__":
    main()
