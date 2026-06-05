r"""
dts_data_pull/backfill.py
=========================
Schedule historical backfills for the native DTS transfers (every GA4 property +
the Google Ads MCC) up to Google's 37-month hard cap.

WHY: a freshly created DTS transfer only loads its rolling refresh window (GA4
default = 4 days), NOT history. To load history you must schedule backfills. This
fans that out across every `ga4` + `google_ads` transfer config in the region.

DTS rules handled here (verified against Google docs, 2026-06):
- Max 180 days per backfill request           -> chunked into <=180-day pieces.
- Backfill range is start-INCLUSIVE, end-EXCLUSIVE.
- 37-MONTH HARD CAP (policy since 2026-06-01): requesting GA4 dates older than
  ~37 months OVERWRITES the BigQuery partition with EMPTY API results = DATA LOSS.
  So START is floored at FLOOR_DATE, kept safely inside 37 months.
  *** DO NOT lower FLOOR_DATE past ~37 months before today. *** (Google Ads errors
  rather than overwrites, so it's safe there, but we use the same floor.)
- GA4 data-retention (2/14 mo) does NOT limit the standard TrafficAcquisition
  report, so the full 37 months is retrievable.
- Each chunk queues one run per day server-side (~10 min/day throttle); the
  perf_* views reflect data as it lands over the following days. Idempotent:
  re-running re-pulls the same partitions (safe, just redundant).
- PER-CONFIG INFLIGHT CAP (300 pending/running runs): you can NOT queue all
  ~1,100 days (37 months) for one config at once. This runs in WAVES -- re-run the
  script every few days; chunks that would exceed the cap fail harmlessly (logged
  as FAIL "...runs currently inflight. Maximum allowable runs inflight") and get
  queued once earlier runs drain. Repeat until the perf_ga4 date range stops growing.

Run:  .\.venv\Scripts\python.exe dts_data_pull\backfill.py [--dry-run]
"""
import json
import subprocess
import sys
from datetime import date, timedelta

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
FLOOR_DATE = date(2023, 6, 1)   # ~36 months back: safely inside the 37-month cap. DO NOT lower.
END_DATE = date(2026, 6, 5)     # end-EXCLUSIVE -> through 2026-06-04 (DTS rejects today/future run times)
CHUNK_DAYS = 180
# GA4 only. Google Ads history is backfilled SEPARATELY by
# backfill_google_ads_history.ps1 + the BidbrainGoogleAdsBackfill scheduled task
# (it walks backward draining the ~300/config inflight cap). Targeting google_ads
# here would just collide with that task's inflight runs.
DATA_SOURCES = ("ga4",)
# GA4 properties whose runs FAIL with PERMISSION_DENIED (ian@100.digital has no GA4
# access to them) -- backfilling is pointless until access is granted. Skip them so we
# don't queue thousands of doomed runs. Remove an ID here once its access is sorted.
SKIP_PROPERTIES = {
    "273098216", "287370621", "341827046", "341832593",
    "358885683", "468621509", "506931798",
}
DRY = "--dry-run" in sys.argv


def bq(args):
    return subprocess.run("bq " + args, shell=True, capture_output=True, text=True)


def list_configs():
    r = bq(f"ls --transfer_config --project_id={PROJECT} --transfer_location={LOCATION} --format=json")
    out = []
    for c in json.loads(r.stdout):
        if c.get("dataSourceId") in DATA_SOURCES:
            p = c.get("params") or {}
            label = p.get("property_id") or p.get("customer_id") or "?"
            if label in SKIP_PROPERTIES:
                continue
            out.append((c["name"], c["dataSourceId"], label))
    return sorted(out, key=lambda x: (x[1], x[2]))


def chunks():
    s = FLOOR_DATE
    while s < END_DATE:
        e = min(s + timedelta(days=CHUNK_DAYS), END_DATE)
        yield s, e
        s = e


def main():
    cfgs = list_configs()
    ch = list(chunks())
    print(f"{'DRY-RUN: ' if DRY else ''}{len(cfgs)} config(s) x {len(ch)} chunk(s) "
          f"[{FLOOR_DATE}..{END_DATE} excl, {CHUNK_DAYS}d] = {len(cfgs) * len(ch)} backfill request(s)")
    ok = fail = 0
    for name, ds, label in cfgs:
        for cs, ce in ch:
            if DRY:
                print(f"  [{ds} {label}] {cs}..{ce}")
                continue
            r = bq(f"mk --transfer_run --start_time={cs}T00:00:00Z --end_time={ce}T00:00:00Z {name}")
            if r.returncode == 0:
                ok += 1
            else:
                fail += 1
                print(f"  FAIL [{ds} {label}] {cs}..{ce}: {(r.stderr or r.stdout).strip()[:140]}")
        print(f"  queued [{ds} {label}]")
    if not DRY:
        print(f"Submitted {ok} backfill request(s), {fail} failed.")


if __name__ == "__main__":
    main()
