"""Feedback Loop - the LIVE read of the Transmission compilation sheet.

This is the production data path for the portal's Feedback Loop pane, and the SINGLE
source of truth for the sheet -> JSON rules (the prototype CLI
prototypes/transmission-feedback-v0/sheet_to_json.py imports build() from here rather
than carrying its own copy).

    Google Sheet "Report Feedback Tracker"  (CSV export, no auth - the sheet is
                 |                           link-shared, so there is no service
                 |                           account or OAuth token to manage)
                 v
    build(csv_text) -> the section-3 data contract  {meta, clients, reports, feedback}
                 v
    main.py _fill_feedback_loop() -> substituted into templates/_feedback_loop_pane.html

Why read at request time rather than shipping a built file: the sheet is edited by hand
whenever a client responds, so anything baked into the image or refreshed on a schedule
is wrong within the hour. load() caches for TTL seconds per instance, so a burst of
portal loads costs one fetch a minute at most.

Fallback chain, so a Google hiccup can never blank the pane:
    fresh fetch  ->  in-memory copy (even if stale)  ->  last-known-good in GCS
    ->  (main.py) the vendored sample file, which flies the amber SAMPLE DATA pill.

Client verbatims NEVER enter git: nothing here writes to the repo. The last-known-good
mirror lives in the platform's own PRIVATE bucket, the same trust boundary as the
feedback widget's recordings.

Governing principle, inherited from the prototype: flag, never guess, never drop
silently. Every judgment call lands in the returned flags list (the CLI prints them
into review_report.txt); nothing is inferred - a sentiment/type/source column that the
sheet does not have stays at its neutral default rather than being guessed from text.
"""

import csv
import io
import json
import os
import re
import threading
import time
from datetime import datetime

SHEET_ID = os.environ.get(
    "FEEDBACK_SHEET_ID", "1dyYciW_xYFDErSrD_SFttmNbIQpsX56_vncVVPMGEbU")
SHEET_GID = os.environ.get("FEEDBACK_SHEET_GID", "0")
SHEET_URL = "https://docs.google.com/spreadsheets/d/%s/edit" % SHEET_ID
CSV_URL = ("https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s"
           % (SHEET_ID, SHEET_GID))
TTL = int(os.environ.get("FEEDBACK_SHEET_TTL", "60"))      # seconds
FETCH_TIMEOUT = float(os.environ.get("FEEDBACK_SHEET_TIMEOUT", "8"))
GCS_OBJECT = "feedback-loop/data.json"                     # last-known-good mirror

CANONICAL_CLIENTS = [
    "Schneider Electric",
    "Schneider - Liquid AI Data Center",
    "Cloudflare",
    "PropTrack",
    "MongoDB",
    "STT",
]

# header -> field key (headers normalised to lowercase collapsed spaces first).
# Only client/campaign/month/submitted/feedback are REQUIRED; every other column is
# optional and simply absent from today's sheet. They are mapped anyway so that the day
# someone adds a Sentiment or Type column the tagging flows straight through to the pane
# with no code change and no redeploy.
HEADER_MAP = {
    "client": "client",
    "campaign": "campaign",
    "month": "month",
    "link to submitted deck": "submitted",
    "link to report deck": "submitted",   # legacy alias
    "link to final deck": "final",
    "client feedback": "feedback",
    # optional, per report
    "sent on": "sent_on",
    "date sent": "sent_on",
    "sent by": "sent_by",
    "report owner": "sent_by",
    "notes": "notes",
    # optional, per feedback entry
    "sentiment": "sentiment",
    "type": "type",
    "feedback type": "type",
    "source": "source",
    "feedback source": "source",
    "author": "author",
    "feedback from": "author",
    "feedback date": "fb_date",
}
REQUIRED = ["client", "campaign", "month", "submitted", "feedback"]  # "final" may be absent

# The pane's enums. Anything outside them is flagged and falls back to the default,
# so a typo in the sheet shows up in the review report instead of silently vanishing
# behind a filter that will never match it.
SENTIMENTS = {"positive": "positive", "negative": "negative", "neutral": "neutral",
              "needs improvement": "negative", "praise": "positive", "good": "positive",
              "bad": "negative", "mixed": "neutral"}
TYPES = {"inaccuracy": "inaccuracy", "incident": "incident", "quality": "quality",
         "delivery": "delivery", "general": "general"}
SOURCES = {"deck_comment": "deck_comment", "deck comment": "deck_comment",
           "email": "email", "slack": "slack", "meeting": "meeting", "call": "call",
           "other": "other"}

MONTH_NAMES = {}
for _i, _name in enumerate(["january", "february", "march", "april", "may", "june", "july",
                            "august", "september", "october", "november", "december"], start=1):
    MONTH_NAMES[_name] = _i
    MONTH_NAMES[_name[:3]] = _i

BULLET_RE = re.compile(r"^\s*(?:[-*•·◦▪–—]+|\d{1,2}[.)])\s+")


# ── parsing helpers ──────────────────────────────────────────────────────────────────
def norm_header(h):
    return re.sub(r"\s+", " ", (h or "").replace("﻿", "").strip().lower())


def parse_month(raw, assume_year):
    """-> (period 'YYYY-MM' or None, note or None). Never raises."""
    s = (raw or "").strip()
    if not s:
        return None, "month cell is empty"
    m = re.match(r"^(\d{4})[-/](\d{1,2})$", s)                      # 2026-06 / 2026/6
    if m:
        return _period(int(m.group(1)), int(m.group(2)), s)
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)                         # 06/2026
    if m:
        return _period(int(m.group(2)), int(m.group(1)), s)
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)               # a full date -> its month
    if m:
        p, note = _period(int(m.group(1)), int(m.group(2)), s)
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


def parse_date(raw):
    """A whole date cell -> ('YYYY-MM-DD' or None, note or None). Day-first on the
    ambiguous d/m/y form: the sheet is filled in by an Australian team."""
    s = (raw or "").strip()
    if not s:
        return None, None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        return _date(int(m.group(1)), int(m.group(2)), int(m.group(3)), s)
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", s)        # 04/08/2026 -> 4 Aug
    if m:
        y = int(m.group(3))
        return _date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)), s)
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s*(\d{4})$", s)  # 4 August 2026
    if m:
        mo = MONTH_NAMES.get(m.group(2).lower())
        if mo:
            return _date(int(m.group(3)), mo, int(m.group(1)), s)
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})$", s)  # August 4, 2026
    if m:
        mo = MONTH_NAMES.get(m.group(1).lower())
        if mo:
            return _date(int(m.group(3)), mo, int(m.group(2)), s)
    return None, "date '%s' not parseable - emitted as null" % s


def _date(y, mo, d, raw):
    try:
        return datetime(y, mo, d).date().isoformat(), None
    except ValueError:
        return None, "date '%s' is not a real date - emitted as null" % raw


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


def _enum(value, table, default, label, rownum, flags):
    v = re.sub(r"\s+", " ", (value or "").strip().lower())
    if not v:
        return default
    if v in table:
        return table[v]
    flags.append((rownum, "%s '%s' is not one of %s - emitted as '%s'"
                  % (label, value.strip(), "/".join(sorted(set(table.values()))), default)))
    return default


# ── the transform ────────────────────────────────────────────────────────────────────
def build(csv_text, sheet_url=SHEET_URL, today=None, live=True, now=None):
    """CSV text -> {data, flags, notes, stats}. `data` is the pane's contract.

    Merging: rows sharing client+campaign+month, or the same submitted-deck URL for the
    same client, are ONE report - their feedback lines combine under a single card. The
    same URL under two DIFFERENT clients is never merged, only flagged.
    """
    now = now or datetime.now().astimezone()
    today = today or now.date()

    rows = list(csv.reader(io.StringIO(csv_text)))
    if not rows:
        raise ValueError("the sheet export is empty")

    headers = [norm_header(h) for h in rows[0]]
    col, unknown_cols = {}, []
    for i, h in enumerate(headers):
        key = HEADER_MAP.get(h)
        if key and key not in col:
            col[key] = i
        elif h:
            unknown_cols.append(rows[0][i])
    missing = [k for k in REQUIRED if k not in col]
    if missing:
        raise ValueError("the sheet is missing required column(s): %s (headers found: %s)"
                         % (", ".join(missing), rows[0]))

    flags, notes = [], []
    if "final" not in col:
        notes.append("The sheet has no 'Link to final deck' column yet - "
                     "deck_final_url emitted as null for every report.")
    if unknown_cols:
        notes.append("Ignored unrecognised column(s): %s." % ", ".join(unknown_cols))
    if "sent_on" not in col and "sent_by" not in col:
        notes.append("The sheet carries no sent-on / sent-by columns - reports emitted with "
                     "sent_on=null, sent_by=\"\" (the card simply omits its 'Sent ...' line).")
    untagged = [c for c in ("sentiment", "type", "source", "author", "fb_date") if c not in col]
    if untagged:
        notes.append("The sheet carries no %s column(s) - those fields keep their neutral "
                     "defaults (sentiment=neutral, type=general, source=other, author=\"\", "
                     "date=null). Tagging is a manual pass in the sheet; nothing is inferred "
                     "from the text." % ", ".join(untagged))

    reports, feedback = [], []
    report_rows = []   # first source row number of each emitted report (for merge messages)
    by_ccm = {}        # (client, campaign_lower, period) -> report index
    by_url = {}        # (client, submitted_url)          -> report index
    url_owner = {}     # submitted_url -> (client, rownum), for cross-client URL reuse
    merged_rows = 0
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
                          "row EXCLUDED from the build (fix the sheet)"
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

        sent_on, note = parse_date(cell(row, "sent_on")) if "sent_on" in col else (None, None)
        if note:
            flags.append((rownum, "sent-on " + note))
        sent_by = cell(row, "sent_by")

        campaign = cell(row, "campaign")
        if not campaign:
            flags.append((rownum, "campaign cell is empty - card title will be blank"))
        campaign_l = campaign.lower()

        # ---- merge detection. A null period never matches on the ccm key (an unknown
        # month is not "the same month").
        idx = how = None
        k_ccm = (client, campaign_l, period)
        if period is not None and k_ccm in by_ccm:
            idx = by_ccm[k_ccm]
            how = "same client/campaign/month as row %d" % report_rows[idx]
        elif submitted and (client, submitted) in by_url:
            idx = by_url[(client, submitted)]
            how = "same submitted-deck URL as row %d" % report_rows[idx]
        if submitted:
            owner = url_owner.get(submitted)
            if owner and owner[0] != client:
                flags.append((rownum, "submitted-deck URL already used by %s (row %d) - NOT "
                              "merged across clients; check the sheet" % (owner[0], owner[1])))

        if idx is not None:
            merged_rows += 1
            r = reports[idx]
            conflicts = []
            if campaign and not r["campaign"]:
                r["campaign"] = campaign
            elif campaign and campaign_l != r["campaign"].lower():
                conflicts.append("campaign differs ('%s' kept)" % r["campaign"])
            if period and not r["period"]:
                r["period"] = period
                by_ccm.setdefault((client, r["campaign"].lower(), period), idx)
            elif period and r["period"] and period != r["period"]:
                conflicts.append("month differs ('%s' kept)" % r["period"])
            if submitted and not r["deck_submitted_url"]:
                r["deck_submitted_url"] = submitted
                by_url[(client, submitted)] = idx
                url_owner.setdefault(submitted, (client, rownum))
            elif submitted and r["deck_submitted_url"] and submitted != r["deck_submitted_url"]:
                conflicts.append("submitted URL differs (first kept)")
            if final and final == r["deck_submitted_url"]:
                conflicts.append("final URL equals the report's submitted URL - ignored (rule 6)")
                final = None
            if final and not r["deck_final_url"]:
                r["deck_final_url"] = final
            elif final and r["deck_final_url"] and final != r["deck_final_url"]:
                conflicts.append("final URL differs (first kept)")
            if sent_on and not r["sent_on"]:
                r["sent_on"] = sent_on
            if sent_by and not r["sent_by"]:
                r["sent_by"] = sent_by
            rid = r["id"]
            flags.append((rownum, "MERGED into report %s (%s) - feedback combined, no duplicate "
                          "card%s" % (rid, how, ("; " + "; ".join(conflicts)) if conflicts else "")))
        else:
            rid = "r-%03d" % (len(reports) + 1)
            reports.append({
                "id": rid,
                "client": client,
                "campaign": campaign,
                "period": period,
                "deck_submitted_url": submitted,
                "deck_final_url": final,
                "sent_on": sent_on,
                "sent_by": sent_by,
                "notes": cell(row, "notes"),
            })
            report_rows.append(rownum)
            if period is not None:
                by_ccm[k_ccm] = len(reports) - 1
            if submitted:
                by_url[(client, submitted)] = len(reports) - 1
                url_owner.setdefault(submitted, (client, rownum))

        sentiment = _enum(cell(row, "sentiment"), SENTIMENTS, "neutral",
                          "sentiment", rownum, flags)
        ftype = _enum(cell(row, "type"), TYPES, "general", "feedback type", rownum, flags)
        source = _enum(cell(row, "source"), SOURCES, "other", "source", rownum, flags)
        author = cell(row, "author")
        fb_date, note = parse_date(cell(row, "fb_date")) if "fb_date" in col else (None, None)
        if note:
            flags.append((rownum, "feedback " + note))

        raw_cell = cell(row, "feedback")
        if not raw_cell:
            flags.append((rownum, "no client feedback text - the report card renders with "
                          "no entries under it"))
        for verbatim in split_feedback(raw_cell):
            feedback.append({
                "id": "f-%03d" % (len(feedback) + 1),
                "report_id": rid,
                "client": client,
                "date": fb_date,
                "author": author,
                "source": source,
                "sentiment": sentiment,
                "type": ftype,
                "verbatim": verbatim,
                "context": raw_cell if raw_cell.strip() != verbatim else "",
            })

    if not reports:
        # Refuse to publish an empty registry (the caltex job pattern): an empty pane is
        # indistinguishable from a broken one, so the caller keeps its last-known-good.
        raise ValueError("the sheet produced no reports - refusing to publish an empty registry")

    periods = sorted(r["period"] for r in reports if r["period"])
    window_start = (periods[0] + "-01") if periods else today.isoformat()

    data = {
        "meta": {
            "generated_at": now.isoformat(timespec="seconds"),
            "sample": False,
            "live": bool(live),
            "window_start": window_start,
            "window_end": today.isoformat(),
            "sheet_url": sheet_url or None,
        },
        "clients": CANONICAL_CLIENTS,
        "reports": reports,
        "feedback": feedback,
    }
    stats = {
        "source_rows": len(data_rows),
        "blank_rows": blank_rows,
        "reports": len(reports),
        "merged_rows": merged_rows,
        "feedback": len(feedback),
        "flags": len(flags),
    }
    return {"data": data, "flags": flags, "notes": notes, "stats": stats}


# ── live read + cache ────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cache = {"json": None, "at": 0.0, "stats": None}    # last good build, this instance


def fetch_csv(url=None, timeout=None):
    """The sheet's CSV export. No auth: the sheet is link-shared, so there is no token
    to hold - which is also why nothing here may ever be exposed on a public route."""
    import requests
    r = requests.get(url or CSV_URL, timeout=timeout or FETCH_TIMEOUT,
                     headers={"User-Agent": "bidbrain-platform/feedback-loop"})
    r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type", ""):
        # Google answers a sign-in page with 200 when the sharing link is revoked.
        raise ValueError("the sheet returned an HTML sign-in page, not CSV - "
                         "check that link sharing is still on")
    r.encoding = "utf-8-sig"
    return r.text


def _gcs_blob():
    bucket = os.environ.get("GCS_BUCKET", "")
    if not bucket:
        return None
    from google.cloud import storage
    return storage.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT",
                                                 "bidbrain-analytics")).bucket(bucket).blob(GCS_OBJECT)


def _mirror_write(text):
    """Keep a last-known-good copy in the platform's PRIVATE bucket, so a Google outage
    shows yesterday's real registry instead of dropping the pane to sample data."""
    try:
        blob = _gcs_blob()
        if blob is None:
            return
        blob.cache_control = "no-store"
        blob.upload_from_string(text, content_type="application/json")
    except Exception:
        pass    # a mirror failure must never break the page


def _mirror_read():
    try:
        blob = _gcs_blob()
        return blob.download_as_text() if blob is not None and blob.exists() else None
    except Exception:
        return None


def load_json(force=False):
    """-> (json_text, source) for the pane, or (None, reason) if every source failed.
    source is one of cache / sheet / memory-stale / gcs, for the server log."""
    with _lock:
        age = time.time() - _cache["at"]
        if _cache["json"] and not force and age < TTL:
            return _cache["json"], "cache"
        try:
            built = build(fetch_csv())
            text = json.dumps(built["data"], ensure_ascii=False)
            _cache.update(json=text, at=time.time(), stats=built["stats"])
            _mirror_write(text)
            return text, "sheet"
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)
            if _cache["json"]:
                # Serve the stale copy but let it age out normally, so the next request
                # retries the sheet rather than pinning to a snapshot.
                return _cache["json"], "memory-stale (%s)" % err
            mirrored = _mirror_read()
            if mirrored:
                return mirrored, "gcs (%s)" % err
            return None, err
