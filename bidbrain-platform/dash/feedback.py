"""Dashboard feedback capture for the platform front-door.

Every proxied dashboard gets a small "Feedback" widget (injected by the reverse proxy in main.py,
exactly like the logout pill). A user can leave TEXT or a VOICE recording — whichever they like —
plus a screenshot of the page they're looking at, and this module persists it to the platform's OWN
private GCS bucket. Same private-bucket trust boundary as the registry. Admins read it back at
/feedback/admin, where each voice note is transcribed and interpreted by AI (see feedback_ai.py).

Layout inside gs://$GCS_BUCKET:
    feedback/<client>/<ts>-<id>.json    # the record (text, refs, and the AI fields once enriched)
    feedback/<client>/<ts>-<id>.<ext>   # the voice recording (only when a voice note was left)
    feedback/<client>/<ts>-<id>.jpg     # the page screenshot (only when one was captured)

Record fields: id, client, text, audio (filename or ""), screenshot (filename or ""), page,
user_kind, created_at (epoch s, UTC), reporter (optional name), deadline (optional preferred
deadline / target deadline, "YYYY-MM-DD" or ""). Enriched later (by main.py via feedback_ai):
transcript, ai_summary, ai_actions[], ai_done. Hand-editable from the tracker (main.py
/feedback/edit): reporter, date_reported (defaults to created_at's date), deadline, text.
"""
import os
import re
import json
import time
import uuid

_PREFIX = "feedback"
MAX_AUDIO_BYTES = 16 * 1024 * 1024     # ~16 MB; the widget caps recording at 2 min (opus is tiny)
MAX_IMAGE_BYTES = 8 * 1024 * 1024      # a JPEG viewport screenshot is normally well under 1 MB
MAX_TEXT_CHARS = 8000

# Triage workflow states for the tracker; a record with no `status` is treated as the first one.
STATUSES = ["Not yet started", "Ongoing", "On Hold", "Completed"]
DEFAULT_STATUS = STATUSES[0]

# MediaRecorder picks a container per browser (Chrome: audio/webm, Safari: audio/mp4). Map the
# mime to a sane extension so the stored object is directly playable in an <audio> tag.
_EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a",
        "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}

_client = None


def _bucket():
    """Lazy, cached storage client (keeps the import off the no-op path; low-traffic so one client)."""
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(os.environ["GCS_BUCKET"])


def _ext_for(ctype):
    return _EXT.get((ctype or "").split(";")[0].strip().lower(), "webm")


def save(client, text, audio_bytes, audio_ctype, page, user_kind, screenshot_bytes=None,
         reporter="", deadline=""):
    """Persist one feedback entry. Returns the stored record dict. `audio_bytes` may be None for a
    text-only note; `screenshot_bytes` is an optional JPEG of the page. `reporter` (name) and
    `deadline` (preferred deadline, "YYYY-MM-DD") are both optional. Order: write the binary
    objects FIRST, then the JSON that references them, so a half-written entry never dangles."""
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    rid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    bucket = _bucket()

    audio_name = ""
    if audio_bytes:
        audio_name = f"{rid}.{_ext_for(audio_ctype)}"
        b = bucket.blob(f"{_PREFIX}/{client}/{audio_name}")
        b.cache_control = "no-store"
        b.upload_from_string(audio_bytes, content_type=(audio_ctype or "audio/webm"))

    shot_name = ""
    if screenshot_bytes:
        shot_name = f"{rid}.jpg"
        b = bucket.blob(f"{_PREFIX}/{client}/{shot_name}")
        b.cache_control = "no-store"
        b.upload_from_string(screenshot_bytes, content_type="image/jpeg")

    rec = {"id": rid, "client": client, "text": text, "audio": audio_name, "screenshot": shot_name,
           "page": (page or "")[:300], "user_kind": user_kind or "", "created_at": int(time.time()),
           "reporter": (reporter or "").strip()[:120], "deadline": (deadline or "").strip()[:40]}
    j = bucket.blob(f"{_PREFIX}/{client}/{rid}.json")
    j.cache_control = "no-store"
    j.upload_from_string(json.dumps(rec, separators=(",", ":")), content_type="application/json")
    return rec


def update_record(client, rid, fields):
    """Merge `fields` into a stored record's JSON (used to write back the AI transcript/summary
    and the triage status)."""
    if not valid(client) or not valid(rid):
        return None
    b = _bucket().blob(f"{_PREFIX}/{client}/{rid}.json")
    if not b.exists():
        return None
    rec = json.loads(b.download_as_bytes())
    rec.update(fields)
    b.cache_control = "no-store"
    b.upload_from_string(json.dumps(rec, separators=(",", ":")), content_type="application/json")
    return rec


def list_recent(limit=300):
    """Every feedback record across all clients, newest first (low volume — a flat scan is fine)."""
    out = []
    for blob in _bucket().list_blobs(prefix=f"{_PREFIX}/"):
        if not blob.name.endswith(".json"):
            continue
        try:
            out.append(json.loads(blob.download_as_bytes()))
        except Exception:
            continue
    out.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return out[:limit]


_SAFE = re.compile(r"^[A-Za-z0-9._-]+$")


def valid(name):
    return bool(_SAFE.match(name or ""))


def delete(client, rid):
    """Delete a record and all its binary objects (json + audio + screenshot share the rid prefix).
    Returns False on an invalid key. Idempotent — deleting an already-gone note is fine."""
    if not valid(client) or not valid(rid):
        return False
    for blob in _bucket().list_blobs(prefix=f"{_PREFIX}/{client}/{rid}"):
        try:
            blob.delete()
        except Exception:
            pass
    return True


def load_blob(client, fname):
    """(bytes, content_type) for one stored file (audio or screenshot), or (None, None). `client`
    and `fname` are validated to bare names so they can't escape the client's feedback folder."""
    if not _SAFE.match(client or "") or not _SAFE.match(fname or ""):
        return None, None
    blob = _bucket().blob(f"{_PREFIX}/{client}/{fname}")
    if not blob.exists():
        return None, None
    blob.reload()
    return blob.download_as_bytes(), (blob.content_type or "application/octet-stream")
