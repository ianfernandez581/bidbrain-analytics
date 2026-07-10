#!/usr/bin/env python
"""
central_scan_test.py — unit test for central_scan.py's PURE classification logic.

The scan's coverage verdict rests entirely on two deterministic, offline functions:
  - pick(cols, pri): which column plays the advertiser / campaign / imp / cost / date role
  - the `delivery` flag: adv AND camp AND (imp OR cost)
A wrong pick silently misclassifies a table (a real delivery table looks empty, or a
lookup table looks like delivery) → a wrong coverage report. So these are worth locking.

No BigQuery, no network — imports central_scan (module-level is import-safe; the bq calls
are all under `if __name__ == '__main__'`) and asserts on synthetic column lists.
Run:  python grid-core/scripts/central_scan_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import central_scan as cs  # noqa: E402

_p, _f = 0, 0


def check(name, cond, got=None):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS", name)
    else:
        _f += 1
        print("  FAIL", name, "" if got is None else repr(got))


def delivery(cols):
    adv = cs.pick(cols, cs.ADV_PRI)
    camp = cs.pick(cols, cs.CAMP_PRI)
    imp = cs.pick(cols, cs.IMP_PRI)
    cost = cs.pick(cols, cs.COST_PRI)
    return bool(adv and camp and (imp or cost))


# --- pick(): exact priority beats substring, and priority order is honoured ---
check("exact match wins over later substring",
      cs.pick(["account_name", "advertiser_name"], cs.ADV_PRI) == "advertiser_name",
      cs.pick(["account_name", "advertiser_name"], cs.ADV_PRI))
check("falls back to substring when no exact",
      cs.pick(["ACCOUNT_NAME_RAW"], cs.ADV_PRI) == "ACCOUNT_NAME_RAW")
check("case-insensitive exact",
      cs.pick(["ADVERTISER_NAME"], cs.ADV_PRI) == "ADVERTISER_NAME")
check("returns None when nothing matches",
      cs.pick(["foo", "bar"], cs.ADV_PRI) is None)
check("cost picks micros/native spellings",
      cs.pick(["metrics_cost_micros"], cs.COST_PRI) is not None
      and cs.pick(["cost_native"], cs.COST_PRI) is not None)

# --- delivery classification on real-world shapes seen in the scan ---
check("Snowflake dv360 shape IS delivery",
      delivery(["ADVERTISER_NAME", "CAMPAIGN_NAME", "IMPRESSIONS", "MEDIA_COST_ADVERTISER_CURRENCY"]))
check("Windsor perf_google_ads shape IS delivery (cost, no imp col named 'impressions')",
      delivery(["account_name", "campaign_name", "impressions", "spend"]))
check("cost-only (no impressions) still delivery",
      delivery(["advertiser_name", "campaign_name", "spend_aud"]))
check("lookup table (no campaign) is NOT delivery",
      not delivery(["account_name", "impressions", "cost"]))
check("dim table (adv+camp but no imp/cost) is NOT delivery",
      not delivery(["advertiser_name", "campaign_name", "country"]))

print("\nRESULT: %d passed, %d failed" % (_p, _f))
sys.exit(1 if _f else 0)
