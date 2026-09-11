#!/usr/bin/env python
"""
config_coverage_test.py - every LIVE client feed must be monitored by config.json.

Why this exists
---------------
The same defect was found three times on 2026-09-11, in three different feeds:

  * sophiie's Trade Desk advertiser (gjcl0pp) - the ONLY feed that dashboard reads
  * geocon's LinkedIn account (556629043) - gates that dashboard's rebuild
  * sophiie's Windsor GA4 property (468621509) - landing data daily

In each case the loader was pulling the data and a client dashboard was reading it, but
`connections/config.json` had no entry, so the Connections tab reported the account as
"Unconfigured / idle" - a state that alerts nobody and reads as "expected to be quiet".
A live client feed can therefore die in total silence, which is the exact failure the
Connections tab was built to prevent.

Two of the three were found only because someone went looking. Nothing would have caught
the fourth. This is that something.

What it checks
--------------
For every clients/client_<c>/sql/*.sql, the `raw_windsor.<table>` references are read out
and mapped back to the datasource that owns that table. The client must then appear in
that datasource's accounts - as `client`, or in some account's `consumers`.

Deliberately NOT hardcoded: the table -> datasource map is derived from config.json's own
`table` fields, so adding a datasource cannot leave this test asserting a stale map.

False positives were the main design risk, since a wrong failure here blocks a deploy for
no reason. Three things guard against one:
  * `--` line comments are stripped first (a table named only in a comment is not a read)
  * NON_CONNECTOR_TABLES lists the raw_windsor tables that are NOT Windsor connector feeds
    (derived breakdowns we build ourselves, lookups, and the unscheduled google_ads
    fallback). They are exempt BY NAME rather than by pattern, so a genuinely new
    ingested table cannot slip through as "probably derived".
  * a client directory with no sql/ is skipped rather than failed.

Run:  python ingest/windsor_data_pull/connections/config_coverage_test.py
      (from the repo root - it reads clients/ and config.json)
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

# raw_windsor tables that are NOT a Windsor connector feed, and why each is exempt.
# Listed by name on purpose: a new ingested table that nobody adds here FAILS, which is
# the point - silence is what this test exists to remove.
NON_CONNECTOR_TABLES = {
    "windsor_fields": "field-metadata lookup, loaded by fields_loader; no per-account health to report",
    "hubspot_owners": "lookup dimension pulled alongside hubspot_contacts, not its own connector",
    "perf_google_ads": "laptop-run fallback; nobody schedules it and the tab monitors the native "
                       "DTS tables instead (dts_google_ads). Deliberately unmonitored.",
    # Derived breakdowns: we BUILD these from a connector table we already monitor, so the
    # health of the underlying feed is what matters and it is covered by that feed's entry.
    "nextsmile_meta_breakdown": "derived from perf_meta, which is monitored",
    "geocon_meta_breakdown": "derived from perf_meta, which is monitored",
    "bellshakespeare_meta_breakdown": "derived from perf_meta, which is monitored",
    "caltex_ttd_geo": "derived from perf_the_trade_desk, which is monitored",
}

_p, _f = 0, 0


def check(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS  " + name)
    else:
        _f += 1
        print("  FAIL  " + name + (("\n         " + detail) if detail else ""))


def strip_sql_comments(sql):
    """`--` to end of line, and /* */ blocks. A table named only in a comment is not a read."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", " ", sql)


def main():
    cfg_path = os.path.join(HERE, "config.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    # table -> datasource, straight from config.json so it cannot go stale
    table_to_ds = {}
    for ds in cfg["datasources"]:
        tbl = ds.get("table") or ""
        if tbl.startswith("raw_windsor."):
            table_to_ds[tbl.split(".", 1)[1]] = ds["ds"]

    # which clients each datasource covers
    covered = {}
    for ds in cfg["datasources"]:
        for a in ds.get("accounts", []):
            for key in list(a.get("consumers") or []) + ([a["client"]] if a.get("client") else []):
                covered.setdefault(key, set()).add(ds["ds"])

    print("table -> datasource (derived from config.json): %d connector tables" % len(table_to_ds))
    print("clients with at least one entry: %d" % len(covered))
    print()

    gaps, unknown = [], []
    for cdir in sorted(glob.glob(os.path.join(ROOT, "clients", "client_*"))):
        client = os.path.basename(cdir)[len("client_"):]
        sqls = glob.glob(os.path.join(cdir, "sql", "*.sql"))
        if not sqls:
            continue
        blob = ""
        for f in sqls:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                blob += strip_sql_comments(fh.read())
        # digits matter: perf_ga4 is silently truncated to perf_ga by [a-z_]+
        for tbl in sorted(set(re.findall(r"raw_windsor\.([a-z0-9_]+)", blob))):
            if tbl in NON_CONNECTOR_TABLES:
                continue
            if tbl not in table_to_ds:
                unknown.append((client, tbl))
                continue
            ds = table_to_ds[tbl]
            if ds not in covered.get(client, set()):
                gaps.append((client, tbl, ds))

    print("every live client feed is monitored")
    check("no client reads a connector table its config does not cover",
          not gaps,
          "\n         ".join(
              "%s reads raw_windsor.%s (datasource '%s') but no account in that datasource "
              "names it - it will show as 'Unconfigured / idle' and alert nobody."
              % (c, t, d) for c, t, d in gaps))

    check("no unrecognised raw_windsor table is read",
          not unknown,
          "\n         ".join(
              "%s reads raw_windsor.%s, which is neither a configured datasource table nor "
              "listed in NON_CONNECTOR_TABLES. If it is a new connector feed, add it to "
              "config.json; if it is derived, add it to NON_CONNECTOR_TABLES with the reason."
              % (c, t) for c, t in unknown))

    print("\nRESULT: %d passed, %d failed" % (_p, _f))
    return 1 if _f else 0


if __name__ == "__main__":
    sys.exit(main())
