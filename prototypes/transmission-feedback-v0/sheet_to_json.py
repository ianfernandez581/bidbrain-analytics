#!/usr/bin/env python3
"""Transmission Feedback Loop - offline/shareable build of the registry.

The compilation sheet  ->  data.json (the section-3 contract)
                       ->  a REAL-DATA build of the prototype page
                       ->  review_report.txt

**The portal no longer needs this script.** Since the live-sheet swap, the Feedback
Loop pane in the agency portal reads the sheet on request
(`bidbrain-platform/dash/feedback_loop_data.py`), so there is nothing to re-run after
someone adds a row. This script remains the way to produce a SNAPSHOT you can hand
someone as a file (meta.live=false, so the page says so), and the way to read the
review report - the flag list of every judgment call the transform made.

The transform itself lives in ONE place, imported below: keeping a second copy of the
month parsing, merge and flagging rules here is how the two would drift apart.

Outputs land in the repo's gitignored staging/ area (default:
staging/transmission-feedback-v0/), NEVER in the tracked prototype folder: client
verbatims must not enter git history. The tracked index.html keeps sample data with
meta.sample=true.

Expected columns (headers matched case-insensitively):
    Client | Campaign | Month | Link to submitted deck | Link to final deck | Client feedback
Optional, honoured when present: Sent on | Sent by | Notes | Sentiment | Type | Source |
Author | Feedback date. "Link to report deck" is a legacy alias for the submitted column.

Usage (from the repo root, with the repo venv):
    .\\.venv\\Scripts\\python.exe prototypes\\transmission-feedback-v0\\sheet_to_json.py
    .\\.venv\\Scripts\\python.exe prototypes\\transmission-feedback-v0\\sheet_to_json.py export.csv
With no CSV argument it pulls the sheet's own CSV export, same as the portal does.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_OUT = REPO / "staging" / "transmission-feedback-v0"

# The single source of truth for the sheet -> JSON rules (also the portal's live path).
sys.path.insert(0, str(REPO / "bidbrain-platform" / "dash"))
import feedback_loop_data as fbl   # noqa: E402


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
    ap = argparse.ArgumentParser(description="Compilation sheet -> Feedback Loop staging build")
    ap.add_argument("csv_path", nargs="?",
                    help="CSV export of the compilation sheet (default: pull it from the sheet)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="output folder (default: %(default)s - gitignored staging)")
    ap.add_argument("--sheet-url", default=fbl.SHEET_URL,
                    help="compilation-sheet URL embedded as meta.sheet_url")
    args = ap.parse_args()

    if args.csv_path:
        src = Path(args.csv_path)
        if not src.exists():
            sys.exit("ERROR: %s not found" % src)
        csv_text = src.read_text(encoding="utf-8-sig")
        source_label = str(src)
    else:
        try:
            csv_text = fbl.fetch_csv()
        except Exception as e:
            sys.exit("ERROR: could not pull the sheet (%s: %s).\n"
                     "Download it by hand (File > Download > CSV) and pass the path instead."
                     % (type(e).__name__, e))
        source_label = fbl.CSV_URL

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()

    try:
        built = fbl.build(csv_text, sheet_url=args.sheet_url, live=False, now=now)
    except ValueError as e:
        sys.exit("ERROR: %s" % e)

    data_text = json.dumps(built["data"], indent=2, ensure_ascii=False)
    (out_dir / "data.json").write_text(data_text, encoding="utf-8")
    inject(HERE / "index.html", data_text, out_dir / "index.html")

    st, flags, notes = built["stats"], built["flags"], built["notes"]
    lines = ["Transmission Feedback Loop - refresh review report",
             "Generated: %s" % now.isoformat(timespec="seconds"),
             "Source: %s (%d data rows, %d blank)"
             % (source_label, st["source_rows"], st["blank_rows"]),
             "",
             "NOTES"]
    lines += ["- " + n for n in notes] or ["(none)"]
    lines += ["", "FLAGS (%d)" % len(flags)]
    lines += ["Row %d: %s" % (rn, reason) for rn, reason in flags] or ["(none)"]
    lines += ["",
              "RECONCILIATION - check these before the file ships",
              "Source data rows: %d (%d blank skipped)" % (st["source_rows"], st["blank_rows"]),
              "Reports emitted: %d" % st["reports"],
              "Rows merged into existing reports: %d" % st["merged_rows"],
              "Feedback entries emitted: %d" % st["feedback"],
              "Review flags: %d" % len(flags),
              ""]
    (out_dir / "review_report.txt").write_text("\n".join(lines), encoding="utf-8")

    print("Source data rows:        %d (%d blank skipped)" % (st["source_rows"], st["blank_rows"]))
    print("Reports emitted:         %d (%d rows merged into existing reports)"
          % (st["reports"], st["merged_rows"]))
    print("Feedback entries emitted: %d" % st["feedback"])
    print("Review flags:            %d  -> %s" % (len(flags), out_dir / "review_report.txt"))
    print("")
    print("Build: %s" % (out_dir / "index.html"))
    print("Next:  1) read the review report and fix flagged sheet rows, then re-run")
    print("       2) share the file via direct message only, never a public link")
    print("       (the portal itself needs no refresh - it reads the sheet live)")


if __name__ == "__main__":
    main()
