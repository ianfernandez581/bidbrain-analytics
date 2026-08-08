#!/usr/bin/env python3
"""Transmission Feedback Loop v0 - sheet refresh.

CSV export of the compilation sheet  ->  data.json (the section-3 contract)
                                     ->  a REAL-DATA build of the prototype page
                                     ->  review_report.txt

Outputs land in the repo's gitignored staging/ area (default:
staging/transmission-feedback-v0/), NEVER in the tracked prototype folder:
client verbatims must not enter git history. The tracked index.html keeps
sample data with meta.sample=true; this script writes its own copy with
meta.sample=false next to data.json and review_report.txt.

Expected CSV columns (headers matched case-insensitively):
    Client | Campaign | Month | Link to submitted deck | Link to final deck | Client feedback
"Link to report deck" is tolerated as a legacy alias for the submitted column.
"Link to final deck" may be absent entirely (the column is being added to the sheet).

Governing principle: flag, never guess, never drop silently. Every judgment
call lands in review_report.txt with its row number; a human checks the
reconciliation counts before the file ships.

Usage (from the repo root, with the repo venv):
    .\\.venv\\Scripts\\python.exe prototypes\\transmission-feedback-v0\\sheet_to_json.py export.csv
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_OUT = REPO / "staging" / "transmission-feedback-v0"
DEFAULT_SHEET_URL = ("https://docs.google.com/spreadsheets/d/"
                     "1dyYciW_xYFDErSrD_SFttmNbIQpsX56_vncVVPMGEbU/edit")

CANONICAL_CLIENTS = [
    "Schneider Electric",
    "Schneider - Liquid AI Data Center",
    "Cloudflare",
    "PropTrack",
    "MongoDB",
    "STT",
]

# header -> field key (headers are normalised to lowercase collapsed spaces first)
HEADER_MAP = {
    "client": "client",
    "campaign": "campaign",
    "month": "month",
    "link to submitted deck": "submitted",
    "link to report deck": "submitted",   # legacy alias
    "link to final deck": "final",
    "client feedback": "feedback",
}
REQUIRED = ["client", "campaign", "month", "submitted", "feedback"]  # "final" may be absent

MONTH_NAMES = {}
for i, name in enumerate(["january", "february", "march", "april", "may", "june", "july",
                          "august", "september", "october", "november", "december"], start=1):
    MONTH_NAMES[name] = i
    MONTH_NAMES[name[:3]] = i

BULLET_RE = re.compile(r"^\s*(?:[-*•·◦▪–—]+|\d{1,2}[.)])\s+")


def norm_header(h):
    return re.sub(r"\s+", " ", (h or "").replace("﻿", "").strip().lower())


def parse_month(raw, assume_year):
    """-> (period 'YYYY-MM' or None, note or None). Never raises."""
    s = (raw or "").strip()
    if not s:
        return None, "month cell is empty"
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", s)                      # 2026-06 / 2026/6
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return _period(y, mo, s)
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)                         # 06/2026
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        return _period(y, mo, s)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)               # a full date -> its month
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        p, note = _period(y, mo, s)
        return p, note or "full date '%s' reduced to its month" % s
    m = re.match(r"^([A-Za-z]{3,9})\.?[\s,\-]*(\d{4})?$", s)        # June / Jun 2026 / June, 2026
    if m:
        mo = MONTH_NAMES.get(m.group(1).lower())
        if mo:
            if m.group(2):
                return _period(int(m.group(2)), mo, s)
            p, note = _period(assume_year, mo, s)
            return p, note or "month '%s' has no year - assumed %d" % (s, assume_year)
    return None, "month '%s' not parseable" % s


def _period(y, mo, raw):
    if 1 <= mo <= 12 and 2000 <= y <= 2100:
        return "%04d-%02d" % (y, mo), None
    return None, "month '%s' out of range" % raw


def clean_url(raw):
    u = (raw or "").strip()
    return u or None


def split_feedback(cell):
    """One sheet cell -> list of verbatim strings (newline / bullet separated)."""
    items = []
    for line in re.split(r"\r?\n", cell or ""):
        line = BULLET_RE.sub("", line).strip()
        if line and not re.fullmatch(r"[-*•·◦▪–—.]+", line):
            items.append(line)
    return items


def closest_client(name):
    import difflib
    hits = difflib.get_close_matches(name, CANONICAL_CLIENTS, n=1, cutoff=0.6)
    return hits[0] if hits else None


def inject(index_src, data_json_text, out_html):
    """Replace the embedded data block in a copy of the prototype page."""
    html = index_src.read_text(encoding="utf-8")
    # "</" inside JSON strings would close the script tag early - escape it (still valid JSON)
    safe = data_json_text.replace("</", "<\\/")
    pattern = re.compile(r'(<script id="data" type="application/json">)(.*?)(</script>)', re.S)
    if not pattern.search(html):
        sys.exit("ERROR: could not find the data block in %s" % index_src)
    html = pattern.sub(lambda m: m.group(1) + "\n" + safe + "\n" + m.group(3), html, count=1)
    out_html.write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Compilation-sheet CSV -> Feedback Loop staging build")
    ap.add_argument("csv_path", help="CSV export of the compilation sheet")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output folder (default: %(default)s - gitignored staging)")
    ap.add_argument("--sheet-url", default=DEFAULT_SHEET_URL,
                    help="compilation-sheet URL embedded as meta.sheet_url")
    args = ap.parse_args()

    src = Path(args.csv_path)
    if not src.exists():
        sys.exit("ERROR: %s not found" % src)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone()
    today = now.date()

    with src.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        rows = [r for r in reader]
    if not rows:
        sys.exit("ERROR: CSV is empty")

    headers = [norm_header(h) for h in rows[0]]
    col = {}
    unknown_cols = []
    for i, h in enumerate(headers):
        key = HEADER_MAP.get(h)
        if key and key not in col:
            col[key] = i
        elif h:
            unknown_cols.append(rows[0][i])
    missing = [k for k in REQUIRED if k not in col]
    if missing:
        sys.exit("ERROR: CSV is missing required column(s): %s\nHeaders found: %s"
                 % (", ".join(missing), rows[0]))

    flags = []          # (row_number, reason) - every judgment call / null
    notes = []          # structural, once-per-run notes
    if "final" not in col:
        notes.append("The sheet has no 'Link to final deck' column yet - "
                     "deck_final_url emitted as null for every report.")
    if unknown_cols:
        notes.append("Ignored unrecognised column(s): %s." % ", ".join(unknown_cols))
    notes.append("The sheet carries no sent-on / sent-by columns - reports emitted with "
                 "sent_on=null, sent_by=\"\" (the card simply omits its 'Sent ...' line).")
    notes.append("The sheet carries no per-entry date/author/sentiment/type/source - feedback "
                 "emitted with date=null, author=\"\", sentiment=neutral, type=general, "
                 "source=other, and the full raw cell in context. Tagging them is a manual "
                 "pass in the sheet afterwards; this script does not infer.")

    reports, feedback = [], []
    seen = {}
    blank_rows = 0
    canon_lower = {c.lower(): c for c in CANONICAL_CLIENTS}

    def cell(row, key):
        i = col.get(key)
        return row[i].strip() if i is not None and i < len(row) else ""

    data_rows = rows[1:]
    for offset, row in enumerate(data_rows):
        rownum = offset + 2  # 1-based, counting the header row
        if not any((c or "").strip() for c in row):
            blank_rows += 1
            continue

        raw_client = cell(row, "client")
        client = canon_lower.get(raw_client.lower())
        if not client:
            near = closest_client(raw_client)
            flags.append((rownum, "client '%s' is not a canonical Transmission client%s - "
                          "row EXCLUDED from the build (fix the sheet and re-run)"
                          % (raw_client, " (did you mean '%s'?)" % near if near else "")))
            continue

        period, note = parse_month(cell(row, "month"), today.year)
        if note:
            if period is None:
                flags.append((rownum, note + " - emitted with period=null "
                              "(surfaces under 'Needs review' in the UI)"))
            else:
                flags.append((rownum, note))

        submitted = clean_url(cell(row, "submitted"))
        final = clean_url(cell(row, "final")) if "final" in col else None
        if final and submitted and final == submitted:
            flags.append((rownum, "final deck URL identical to the submitted URL - "
                          "deck_final_url set to null (the deck was likely edited in place; "
                          "preserve the submitted version as its own file)"))
            final = None
        for label, u in (("submitted", submitted), ("final", final)):
            if u and not re.match(r"^https?://", u, re.I):
                flags.append((rownum, "%s deck URL does not look like a link: '%s' "
                              "(emitted as-is; the UI will not render it)" % (label, u)))
        if not submitted:
            flags.append((rownum, "no submitted-deck link - card renders without a deck link"))

        campaign = cell(row, "campaign")
        if not campaign:
            flags.append((rownum, "campaign cell is empty - card title will be blank"))

        dup_key = (client, campaign.lower(), period)
        if dup_key in seen:
            flags.append((rownum, "duplicate of row %d (same client/campaign/month) - "
                          "both emitted; merge them in the sheet if unintended" % seen[dup_key]))
        else:
            seen[dup_key] = rownum

        rid = "r-%03d" % (len(reports) + 1)
        reports.append({
            "id": rid,
            "client": client,
            "campaign": campaign,
            "period": period,
            "deck_submitted_url": submitted,
            "deck_final_url": final,
            "sent_on": None,
            "sent_by": "",
            "notes": "",
        })

        raw_cell = cell(row, "feedback")
        for verbatim in split_feedback(raw_cell):
            feedback.append({
                "id": "f-%03d" % (len(feedback) + 1),
                "report_id": rid,
                "client": client,
                "date": None,
                "author": "",
                "source": "other",
                "sentiment": "neutral",
                "type": "general",
                "verbatim": verbatim,
                "context": raw_cell if raw_cell.strip() != verbatim else "",
            })

    periods = sorted(r["period"] for r in reports if r["period"])
    window_start = (periods[0] + "-01") if periods else today.isoformat()

    data = {
        "meta": {
            "generated_at": now.isoformat(timespec="seconds"),
            "sample": False,
            "window_start": window_start,
            "window_end": today.isoformat(),
            "sheet_url": args.sheet_url or None,
        },
        "clients": CANONICAL_CLIENTS,
        "reports": reports,
        "feedback": feedback,
    }
    data_text = json.dumps(data, indent=2, ensure_ascii=False)

    (out_dir / "data.json").write_text(data_text, encoding="utf-8")
    inject(HERE / "index.html", data_text, out_dir / "index.html")

    lines = ["Transmission Feedback Loop - refresh review report",
             "Generated: %s" % now.isoformat(timespec="seconds"),
             "Source: %s (%d data rows, %d blank)" % (src, len(data_rows), blank_rows),
             "",
             "NOTES"]
    lines += ["- " + n for n in notes]
    lines += ["", "FLAGS (%d)" % len(flags)]
    lines += ["Row %d: %s" % (rn, reason) for rn, reason in flags] or ["(none)"]
    lines += ["",
              "RECONCILIATION - check these before the file ships",
              "Source data rows: %d (%d blank skipped)" % (len(data_rows), blank_rows),
              "Reports emitted: %d" % len(reports),
              "Feedback entries emitted: %d" % len(feedback),
              "Review flags: %d" % len(flags),
              ""]
    (out_dir / "review_report.txt").write_text("\n".join(lines), encoding="utf-8")

    print("Source data rows:        %d (%d blank skipped)" % (len(data_rows), blank_rows))
    print("Reports emitted:         %d" % len(reports))
    print("Feedback entries emitted: %d" % len(feedback))
    print("Review flags:            %d  -> %s" % (len(flags), out_dir / "review_report.txt"))
    print("")
    print("Build: %s" % (out_dir / "index.html"))
    print("Next:  1) read the review report and fix flagged sheet rows, then re-run")
    print("       2) open the build - the amber SAMPLE DATA pill must be GONE")
    print("       3) share the file via direct message only, never a public link")


if __name__ == "__main__":
    main()
