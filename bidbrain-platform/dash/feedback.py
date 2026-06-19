"""Dashboard feedback capture for the platform front-door.

Every proxied dashboard gets a small "Feedback" widget (injected by the reverse proxy in main.py,
exactly like the logout pill). A user can leave TEXT or a VOICE recording — whichever they like —
and this module persists it to the platform's OWN private GCS bucket. No email, no database: the
same private-bucket trust boundary that already holds the registry. Admins read it back at
/feedback/admin.

Layout inside gs://$GCS_BUCKET:
    feedback/<client>/<ts>-<id>.json    # {id, client, text, audio, page, user_kind, created_at}
    feedback/<client>/<ts>-<id>.<ext>   # the voice recording (ONLY when a voice note was left)

`created_at` is epoch seconds (UTC). `audio` is the bare recording filename within the client
folder ("" for a text-only note) — the admin page streams it back via /feedback/audio/<client>/<f>.
"""
import os
import re
import json
import time
import uuid

_PREFIX = "feedback"
MAX_AUDIO_BYTES = 16 * 1024 * 1024     # ~16 MB; the widget caps recording at 2 min (opus is tiny)
MAX_TEXT_CHARS = 8000

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


def save(client, text, audio_bytes, audio_ctype, page, user_kind):
    """Persist one feedback entry. Returns the stored record dict. `audio_bytes` may be None/empty
    for a text-only note. Order: write the audio object FIRST, then the JSON that references it, so
    a half-written entry never points at a missing recording."""
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    rid = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    bucket = _bucket()

    audio_name = ""
    if audio_bytes:
        ext = _ext_for(audio_ctype)
        audio_name = f"{rid}.{ext}"
        b = bucket.blob(f"{_PREFIX}/{client}/{audio_name}")
        b.cache_control = "no-store"
        b.upload_from_string(audio_bytes, content_type=(audio_ctype or "audio/webm"))

    rec = {"id": rid, "client": client, "text": text, "audio": audio_name,
           "page": (page or "")[:300], "user_kind": user_kind or "", "created_at": int(time.time())}
    j = bucket.blob(f"{_PREFIX}/{client}/{rid}.json")
    j.cache_control = "no-store"
    j.upload_from_string(json.dumps(rec, separators=(",", ":")), content_type="application/json")
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


def load_audio(client, fname):
    """(bytes, content_type) for one recording, or (None, None). `fname` is validated to a bare
    filename so it can't escape the client's feedback folder."""
    if not _SAFE.match(client or "") or not _SAFE.match(fname or ""):
        return None, None
    blob = _bucket().blob(f"{_PREFIX}/{client}/{fname}")
    if not blob.exists():
        return None, None
    blob.reload()
    return blob.download_as_bytes(), (blob.content_type or "application/octet-stream")
