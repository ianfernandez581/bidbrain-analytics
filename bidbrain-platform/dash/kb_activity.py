"""kb_activity.py - the usage record, and the store the Observability page reads back.

ONE OBJECT PER EVENT, under `kb/activity/<YYYY-MM>/<ts>-<rand>.json`.

🔴 NOT A `.jsonl` FILE THAT GETS APPENDED TO, because GCS objects cannot be appended to. Anything
that looks like appending is really read-modify-write, and this is the highest frequency write in
the whole system across several Cloud Run instances: two questions in the same second would cost
one of them its record, silently, and the panel that exists to show what the system did would be
quietly wrong about it. One small immutable object per event has no race to lose.

The month prefix is what keeps a read cheap: the panel lists one month, not the whole history.

🔴 A USAGE LOG MAY NEVER FAIL A REQUEST. Every writer here is wrapped by its caller and a failure
is logged at debug. An upload that 500s because the analytics write timed out would be a strictly
worse product than one with a gap in its analytics.

This is ALSO the observability trace store. A question's record carries its scope, latency, model,
passage count, whether the semantic half ran, and WHICH documents came back, which is what lets the
page answer "why did it say that?" for a question asked five minutes ago on another instance. An
in-process ring buffer could not: the instance that served the question is rarely the one serving
the page.
"""
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import kb_store

_log = logging.getLogger(__name__)

PREFIX = "activity"
# What one event may carry. A question's text is kept (it is the point of the record) but bounded,
# and a passage's TEXT is never written here: the document id and ordinal identify it, and the
# passage itself is in the library where it belongs.
MAX_FIELD_CHARS = 2_000
# How many months back the panel will look when it wants "recent". Two covers a month boundary.
LOOKBACK_MONTHS = 2

# `log_event` does NOT validate against this list - it is the roster of what actually gets written,
# so a reader knows what it may encounter. Grouped, because the Meetings page and the Observability
# page each want one group and neither wants the other's (Jerome, 2026-09-17: "it might get confusing
# because it can get mixed to the audit of other process"). `kind_group()` is the single place that
# mapping lives; a new kind is added here and nowhere else.
KINDS = ("search", "question", "doc_added", "doc_edited", "doc_deleted", "doc_moved",
         "folder_renamed", "feedback",
         # meetings (kb_fathom_routes, 2026-09-17): one event per DECISION, not per API call.
         "meeting_filed",     # a rung or the model placed it with no human involved
         "meeting_queued",    # not sure enough - it went to the queue to wait for a person
         "meeting_assigned",  # a person confirmed or chose the client, FROM THE QUEUE
         "meeting_ignored",   # a person said this belongs in the library at all
         "meeting_moved",     # an ALREADY-FILED meeting was re-filed to a different client
         "meeting_rebuilt")   # an already-filed meeting's document was regenerated

# 🔴 `meeting_assigned` AND `meeting_moved` ARE NOT THE SAME EVENT, and collapsing them makes the
# audit trail lie. Assigned means somebody worked the queue: the meeting was waiting, they chose.
# Moved means it had already been filed and was corrected afterwards - nobody confirmed anything.
# Logged as "assigned" on 2026-09-17, four script-applied corrections made Observability report
# "4 confirmed by a person" on a day nobody had touched the queue. Jerome spotted it on the tile.

GROUPS = {"questions": ("search", "question", "feedback"),
          "documents": ("doc_added", "doc_edited", "doc_deleted", "doc_moved", "folder_renamed"),
          "meetings": ("meeting_filed", "meeting_queued", "meeting_assigned", "meeting_ignored",
                       "meeting_moved", "meeting_rebuilt")}


def kind_group(kind):
    """'meeting_filed' -> 'meetings'. Unknown kinds fall to 'other' rather than being hidden: a kind
    nobody mapped is exactly the thing an audit view must not silently drop."""
    for g, kinds in GROUPS.items():
        if kind in kinds:
            return g
    return "other"


def _month(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m")


def _clip(v):
    if isinstance(v, str):
        return v[:MAX_FIELD_CHARS]
    if isinstance(v, (list, tuple)):
        return [_clip(x) for x in v][:64]
    if isinstance(v, dict):
        return {str(k)[:80]: _clip(x) for k, x in list(v.items())[:32]}
    return v


def log_event(kind, *, actor="", **fields):
    """Write one event. Returns its id, or "" when it could not be written."""
    ts = time.time()
    rec = {"at": int(ts), "kind": str(kind)[:40], "actor": (actor or "")[:200]}
    for k, v in fields.items():
        rec[str(k)[:40]] = _clip(v)
    name = "%s/%013d-%s.json" % (_month(ts), int(ts * 1000), uuid.uuid4().hex[:6])
    try:
        b = kb_store._blob(f"{PREFIX}/{name}")          # noqa: SLF001 - same storage layer
        b.cache_control = "no-store"
        b.upload_from_string(json.dumps(rec, ensure_ascii=False),
                             content_type="application/json")
    except Exception:                                  # noqa: BLE001 - see the module header
        _log.debug("kb_activity: could not write %s", kind, exc_info=True)
        return ""
    return name


# The name kb_routes calls. Kept short because it appears at the end of every write path.
# 🔴 The module logger is `_log`, not `log`, precisely because this alias exists: named `log` it
# would shadow the logger and every failure path in `log_event` would raise instead of recording.
log = log_event


def months(back=LOOKBACK_MONTHS):
    """The month prefixes to read for a "recent" view, newest first."""
    now = datetime.now(timezone.utc)
    out = []
    y, m = now.year, now.month
    for _ in range(max(1, back)):
        out.append("%04d-%02d" % (y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def read_month(ym, limit=5000):
    """Every event in one month, oldest first. The object NAME sorts by time, so the listing is
    already in order and nothing has to be sorted after reading."""
    from concurrent.futures import ThreadPoolExecutor
    client = kb_store._storage()                        # noqa: SLF001
    names = []
    base = f"{kb_store.PREFIX}/{PREFIX}/{ym}/"
    for b in client.list_blobs(kb_store.bucket_name(), prefix=base):
        if b.name.endswith(".json"):
            names.append(b.name)
    names.sort()
    names = names[-limit:]
    if not names:
        return []
    bucket = client.bucket(kb_store.bucket_name())

    def read(n):
        try:
            return json.loads(bucket.blob(n).download_as_bytes().decode("utf-8"))
        except Exception:                              # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=24) as pool:
        return [r for r in pool.map(read, names) if isinstance(r, dict)]


def recent(back=LOOKBACK_MONTHS, limit=5000):
    """Events across the last few months, oldest first."""
    out = []
    for ym in reversed(months(back)):                   # oldest month first
        out.extend(read_month(ym, limit=limit))
    return out[-limit:]


# --- what the Observability page shows ----------------------------------------------------------

def summarise(events, known_doc_ids=None):
    """Turn the raw record into the five things the panel states. Every number here is counted from
    events, never estimated, so a panel that says "3 questions this week" means three records
    exist."""
    questions = [e for e in events if e.get("kind") in ("search", "question")]
    asked = [e for e in events if e.get("kind") == "question"] or questions
    feedback = [e for e in events if e.get("kind") == "feedback"]

    by_week = {}
    for e in questions:
        wk = datetime.fromtimestamp(e.get("at") or 0, timezone.utc).strftime("%G-W%V")
        by_week[wk] = by_week.get(wk, 0) + 1

    retrieved = {}
    for e in questions:
        for d in (e.get("docs") or []):
            retrieved[d] = retrieved.get(d, 0) + 1

    keyword_only = sum(1 for e in questions if e.get("semantic") is False)
    lat = sorted(int(e.get("ms") or 0) for e in asked if e.get("ms"))

    never = []
    if known_doc_ids:
        never = sorted(set(known_doc_ids) - set(retrieved))

    return {
        "questions": len(questions),
        "answers": len(asked),
        "by_week": [{"week": w, "count": c} for w, c in sorted(by_week.items())],
        "top_documents": sorted(({"id": d, "count": c} for d, c in retrieved.items()),
                                key=lambda r: -r["count"])[:20],
        "never_retrieved": never,
        "feedback": len(feedback),
        # A rate, and the denominator is stated beside it, because a bare percentage over three
        # questions reads like a measurement.
        "feedback_rate": (round(len(feedback) / len(asked), 3) if asked else None),
        "keyword_only": keyword_only,
        "keyword_only_rate": (round(keyword_only / len(questions), 3) if questions else None),
        "median_ms": (lat[len(lat) // 2] if lat else None),
        "p90_ms": (lat[int(len(lat) * 0.9)] if lat else None),
        "documents_added": sum(1 for e in events if e.get("kind") == "doc_added"),
        "documents_edited": sum(1 for e in events if e.get("kind") == "doc_edited"),
    }
