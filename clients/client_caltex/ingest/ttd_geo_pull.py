r"""
Caltex-ONLY Trade Desk GEO pull - real delivery by Australian region/state.

WHY THIS EXISTS. The dashboard's "market" is parsed out of the ad-group NAME ("Tactic | Market"),
so every row reads `QLD+WA` - one lump, no per-state visibility, and nothing else can ever appear
no matter where the ads actually served. Probing Windsor's TTD `region` field on 2026-08-12 showed
the campaign IS delivering into SOUTH AUSTRALIA (~6% of impressions: Adelaide Central/North/West/
South, Barossa, South East, Outback) while the ad group still says QLD+WA. Real geo is the only
honest way to show that.

ISOLATION (by design - this cannot affect any other client):
  * Separate script; does NOT import or touch ingest/windsor_data_pull/tradedesk/tradedesk_loader.py.
  * Writes a NEW caltex-only table `raw_windsor.caltex_ttd_geo`. It does NOT write
    perf_the_trade_desk.
  * Read-only Windsor calls, filtered to advertiser 0lw3hp6 before anything is written.

The shared perf_the_trade_desk CANNOT carry `region`: it multiplies the grain ~29x (measured:
50 -> 1,462 rows for one seat over 3 days) and that table feeds FIVE TTD clients (caltex, vmch,
tlm, cityperfume, resetdata). Same reasoning as client_geocon/ingest/meta_breakdown_pull.py.

Region strings arrive as "State - Area - Sub" (e.g. "Queensland - Brisbane - Inner City"); the
STATE is the first ' - ' segment and is derived here so the view/dashboard never re-parse it.

RUN (key from Secret Manager via the gcloud CLI, so no ADC needed):
    WINDSOR_API_KEY="$(gcloud secrets versions access latest --secret=windsor-api-key | tr -d '\r\n')" \
      python clients/client_caltex/ingest/ttd_geo_pull.py 2026-07-28 2026-08-11 out.ndjson
then:
    bq load --replace --source_format=NEWLINE_DELIMITED_JSON \
      raw_windsor.caltex_ttd_geo out.ndjson \
      date:DATE,campaign:STRING,ad_group_name:STRING,region:STRING,state:STRING,impressions:INTEGER,clicks:INTEGER,spend:FLOAT
then reapply views + force the export:
    .\.venv\Scripts\python.exe clients\client_caltex\create_views.py
    gcloud run jobs execute caltex-export --region australia-southeast1 --update-env-vars FORCE_REBUILD=1 --wait

NOT SCHEDULED (same as the geocon breakdown pull): re-run it manually when the geo view needs
refreshing, or wire it into scheduler.ps1 once the client relies on it day to day.
"""
import os, sys, json, time, requests
from datetime import date, timedelta

ADVERTISER = "0lw3hp6"                       # Caltex Star Card
ACCOUNT = "569"                              # the agency TTD seat Windsor exposes
                                             # (was 484; the 2026-08-25 re-grant issued a new seat id)
URL = "https://connectors.windsor.ai/tradedesk"
FIELDS = ("advertiser_id,advertiser,date,campaign,ad_group_name,region,"
          "impressions,clicks,advertiser_cost_adv_currency")
# CHUNKED, like the shared loader. `region` multiplies the grain ~29x, so a whole flight in one
# request times out (measured: 3 days = 3s, 15 days = dead at 300s). 3-day chunks keep each call
# small and let a slow window fail on its own instead of losing the run.
CHUNK_DAYS = 3
TIMEOUT_SEC = 300
MAX_ATTEMPTS = 6


def ni(v):
    if v in (None, "", "null"): return None
    try: return int(float(v))
    except (TypeError, ValueError): return None


def nf(v):
    if v in (None, "", "null"): return None
    try: return float(v)
    except (TypeError, ValueError): return None


def state_of(region):
    """'Queensland - Brisbane - Inner City' -> 'Queensland'. A bare 'Queensland' stays as-is;
    an empty/unknown region becomes None so the view can show it as Unattributed rather than
    silently folding it into a real state."""
    s = (region or "").strip()
    if not s:
        return None
    return s.split(" - ")[0].strip() or None


def fetch(key, d_from, d_to):
    """One chunk, with retries. Returns [] for a window Windsor will not serve rather than
    aborting the whole pull - a single unavailable day must not cost the other two weeks."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            r = requests.get(URL, params={"api_key": key, "date_from": d_from, "date_to": d_to,
                                          "fields": FIELDS, "select_accounts": ACCOUNT},
                             timeout=TIMEOUT_SEC)
            if r.status_code == 400 and not r.text.strip():
                # Same "day not published yet" signature the shared loader handles: an instant,
                # empty-bodied 400. Retrying cannot publish it, so skip the chunk.
                print(f"  {d_from}..{d_to}: not published yet - skipped")
                return []
            r.raise_for_status()
            rows = r.json().get("data", [])
            print(f"  {d_from}..{d_to}: {len(rows)} rows in {time.monotonic()-t0:.0f}s")
            return rows
        except Exception as e:
            print(f"  {d_from}..{d_to}: attempt {attempt}/{MAX_ATTEMPTS} "
                  f"{type(e).__name__} after {time.monotonic()-t0:.0f}s")
            time.sleep(5)
    print(f"  {d_from}..{d_to}: GIVING UP on this chunk")
    return []


def main():
    key = os.environ["WINDSOR_API_KEY"]
    d_from, d_to, out = sys.argv[1], sys.argv[2], sys.argv[3]
    start, end = date.fromisoformat(d_from), date.fromisoformat(d_to)

    rows = []
    cur = start
    while cur <= end:
        ce = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        rows.extend(fetch(key, cur.isoformat(), ce.isoformat()))
        cur = ce + timedelta(days=1)

    kept = 0
    states = {}
    with open(out, "w", encoding="utf-8") as f:
        for x in rows:
            # Filter to Caltex BEFORE writing anything - this file must never carry another
            # advertiser's delivery, even though the seat request returns the whole account.
            if x.get("advertiser_id") != ADVERTISER and \
               not str(x.get("advertiser", "")).lower().startswith("caltex"):
                continue
            st = state_of(x.get("region"))
            f.write(json.dumps({
                "date": x.get("date"), "campaign": x.get("campaign"),
                "ad_group_name": x.get("ad_group_name"),
                "region": x.get("region"), "state": st,
                "impressions": ni(x.get("impressions")), "clicks": ni(x.get("clicks")),
                "spend": nf(x.get("advertiser_cost_adv_currency")),
            }) + "\n")
            kept += 1
            states[st or "(unattributed)"] = states.get(st or "(unattributed)", 0) + (ni(x.get("impressions")) or 0)

    print(f"{len(rows)} rows fetched for the seat, {kept} Caltex rows written -> {out}")
    for s, i in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"   {s:<24} {i:>9,} impressions")


if __name__ == "__main__":
    main()
