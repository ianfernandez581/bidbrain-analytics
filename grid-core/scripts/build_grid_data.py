#!/usr/bin/env python
"""
================================ RETIRED — PHASE 1 ================================
build_grid_data.py is RETIRED FOR APP DATA. Pulse and Register now read the live
SQLite DB via /api/central/campaigns + src/central/calc.js (the single engine);
the `const DATA = [...]` literal this script rewrote NO LONGER EXISTS in
the-grid.html, and the hardcoded SNAP anchor is replaced by the DB's newest
lastSyncedAt. Running it now exits immediately (see main()). Phase 4 handles
final deletion. The description below is kept as historical reference only.
===================================================================================

build_grid_data.py — regenerate The Grid's embedded campaign array from the
source pacing sheet.

The Grid (`the-grid.html`) renders a `const DATA = [ ... ];` literal that is a
transcription of `bidbrain-platform/Data/Central2.xlsx` ("Live Campaigns"). That
literal was hand-pasted once and drifts stale as the sheet grows (new campaigns,
new clients, updated spend). This script re-reads the committed sheet and rewrites
the DATA literal in place, so the grid always matches the sheet for EVERY client.

Only the raw sheet columns are emitted; the grid derives pacing/margin/projection
at runtime (see `derive()` in the-grid.html), so this is purely the data layer.

Usage (from repo root, with the repo venv):
    .venv/Scripts/python.exe grid-core/scripts/build_grid_data.py            # rewrite in place
    .venv/Scripts/python.exe grid-core/scripts/build_grid_data.py --check    # print counts, write nothing

The two agency header labels and the column order are pinned to the sheet; if the
sheet's layout changes, update HEADER_ROW / COLS below.
"""
import sys

# PHASE 1 KILL SWITCH — fires before anything else so retirement is deterministic
# on every machine. See the retirement header above; Phase 4 deletes this file.
sys.exit("build_grid_data.py is RETIRED (Phase 1): Pulse/Register read the live "
         "SQLite DB via /api/central/campaigns + src/central/calc.js. There is no "
         "const DATA literal to rewrite any more.")

import argparse
import datetime
import json
import re
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parents[2]
SHEET = REPO / "bidbrain-platform" / "Data" / "Central2.xlsx"
GRID = REPO / "grid-core" / "the-grid.html"
SHEET_NAME = "Live Campaigns "        # trailing space is real
HEADER_ROW = 1                        # 0-based index of the header row
AGENCIES = {"100% DIGITAL", "TRANSMISSION"}

# sheet column index -> DATA key + coercion kind. Order here is the emit order.
COLS = [
    (1,  "jobNumber",       "jobstr"),
    (2,  "campaign",        "text"),
    (3,  "objective",       "text"),
    (4,  "channel",         "text"),
    (5,  "managedBy",       "text"),
    (6,  "status",          "text"),
    (7,  "start",           "date"),
    (8,  "end",             "date"),
    (9,  "campaignMargin",  "num"),
    (10, "platformMargin",  "num"),
    (11, "adServing",       "num"),
    (12, "adservingCost",   "num"),
    (13, "forecastCPM",     "num"),
    (14, "cpmPerf",         "num"),
    (15, "keyKPI",          "text"),
    (16, "kpiPerf",         "text"),
    (17, "budgetGross",     "num"),
    (18, "totalBudget",     "num"),
    (19, "impressions",     "num"),
    (20, "mediaSpend",      "num"),
    (21, "clientSpent",     "num"),
    (22, "budgetRemaining", "num"),
    (23, "pctSpent",        "num4"),
    (24, "pctElapsed",      "num4"),
    (26, "campaignLink",    "text"),
    (27, "nextReport",      "datestr"),
    (28, "notes",           "text"),
]

_NULLS = {"", "NA", "N/A", "-", "TBC", "TBD"}


def _text(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.upper() in _NULLS else s


def _num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
    if s.upper() in _NULLS:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return None


def _jobstr(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s.upper() in _NULLS else s


def _datestr(v):
    """Next-reporting cell: a real date -> YYYY-MM-DD, else the text ('Sent', '21/04')."""
    d = _date(v)
    if d:
        return d
    return _text(v)


_COERCE = {"text": _text, "num": _num, "num4": lambda v: (round(_num(v), 4) if _num(v) is not None else None),
           "date": _date, "jobstr": _jobstr, "datestr": _datestr}


def _raw_rows():
    wb = openpyxl.load_workbook(SHEET, data_only=True, read_only=True)
    return list(wb[SHEET_NAME].iter_rows(values_only=True))


def compute_asof(rows):
    """Recover the sheet's real 'as of' date. The sheet's `% Flight Elapsed`
    column (24) = (asof - start)/(end - start), so any mid-flight row implies a
    date; the median across all of them is the sheet's snapshot date. This is
    what the grid's pacing math (SNAP) must be anchored to, so run-rate
    projections match the sheet instead of drifting."""
    implied = []
    agency_seen = False
    for r in rows[HEADER_ROW + 1:]:
        start, end, elap = (r[7] if len(r) > 7 else None), (r[8] if len(r) > 8 else None), (r[24] if len(r) > 24 else None)
        if isinstance(start, datetime.datetime) and isinstance(end, datetime.datetime) and isinstance(elap, (int, float)):
            span = (end - start).days
            if span > 0 and 0.02 < elap < 0.98:      # strictly mid-flight (not clamped at 0/1)
                implied.append((start + datetime.timedelta(days=elap * span)).date())
    if not implied:
        return None
    implied.sort()
    return implied[len(implied) // 2]


def build_rows(rows=None):
    if rows is None:
        rows = _raw_rows()
    out = []
    agency = None
    advertiser = None
    for r in rows[HEADER_ROW + 1:]:
        c0 = str(r[0]).strip() if r[0] is not None else ""
        if c0 in AGENCIES:
            agency = c0
            advertiser = None
            continue
        if c0:
            advertiser = c0
        # a data row must carry a campaign or a channel; otherwise it is a spacer
        if not (r[2] or r[4]):
            continue
        rec = {"agency": agency, "advertiser": advertiser}
        for idx, key, kind in COLS:
            val = r[idx] if idx < len(r) else None
            rec[key] = _COERCE[kind](val)
        out.append(rec)
    return out


def render_literal(rows):
    # one object per line, matching the existing single-line-array style closely enough
    # (JS parses it identically); compact separators keep the file small.
    return "const DATA = " + json.dumps(rows, separators=(", ", ": "), ensure_ascii=False) + ";"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print a per-advertiser count, write nothing")
    ap.add_argument("--no-live", action="store_true", help="skip the BigQuery live-metrics overlay (sheet numbers only)")
    args = ap.parse_args()

    raw = _raw_rows()
    rows = build_rows(raw)
    asof = compute_asof(raw)
    from collections import Counter
    counts = Counter(r["advertiser"] for r in rows)
    print(f"parsed {len(rows)} rows across {len(counts)} advertisers:")
    for k, v in counts.most_common():
        print(f"  {v:3d}  {k}")
    print(f"sheet as-of date (for SNAP): {asof}")

    # Overlay live BigQuery metrics (spend/imps/clicks) onto the sheet-seeded rows,
    # and write a sheet-vs-BQ reconciliation report. Never blocks the sheet regen:
    # a BQ hiccup leaves every row on its sheet number, tagged 'sheet'.
    if not args.no_live:
        try:
            import live_metrics
            live = live_metrics.fetch()
            base = live_metrics.baseline_from(rows)
            n = live_metrics.overlay(rows, live)
            recon = live_metrics.reconcile(base, live)
            print(f"live overlay: {n} rows now BQ-sourced ({len(live)} live keys); reconciliation -> {recon.relative_to(REPO)}")
        except Exception as e:  # noqa: BLE001 - degrade to sheet numbers, never crash the regen
            print(f"live overlay SKIPPED ({e.__class__.__name__}: {str(e)[:200]}); rows stay on sheet numbers")
            for r in rows:
                r.setdefault("metricsSource", "sheet")

    if args.check:
        return

    html = GRID.read_text(encoding="utf-8")
    # the literal is exactly one physical line; anchor to it so nothing else is touched
    pattern = re.compile(r"^const DATA = \[.*\];$", re.MULTILINE)
    if not pattern.search(html):
        sys.exit("ERROR: could not find the `const DATA = [...];` literal in the-grid.html")
    # pass the replacement via a function so re.sub does not interpret backslashes in notes
    new_html = pattern.sub(lambda _m: render_literal(rows), html, count=1)

    # Anchor the grid's pacing 'today' to the sheet's real as-of date, so run-rate
    # projections match the sheet instead of drifting from a stale hardcoded date.
    if asof:
        snap_pat = re.compile(r"(const SNAP=new Date\(')[^']*('\))")
        if not snap_pat.search(new_html):
            sys.exit("ERROR: could not find the `const SNAP=new Date('...')` declaration in the-grid.html")
        new_html = snap_pat.sub(lambda m: f"{m.group(1)}{asof.isoformat()}T00:00:00{m.group(2)}", new_html, count=1)

    GRID.write_text(new_html, encoding="utf-8")
    print(f"\nrewrote {GRID.relative_to(REPO)} with {len(rows)} rows; SNAP -> {asof}")


if __name__ == "__main__":
    main()
