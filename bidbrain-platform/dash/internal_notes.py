"""Internal Notes - the staff-only note pad behind every proxied dashboard.

The proxy injects an "Internal Notes" tab-widget into each dashboard for superadmin / admin /
the client's OWNING agency (never a client session - see _internal_allowed in main.py). Notes are
free-text observations the team wants to keep next to the numbers ("TTD spend dipped w/c 07-28,
Windsor lag, not real", "client asked to hide Reddit until re-auth", ...). The internal AI
assistant (internal_chat.py) reads them as context and can add/edit/delete them via tool calls.

Storage: ONE JSON blob per client in the platform's own private bucket - the same trust boundary
as the registry and feedback:
    internal_notes/<client>.json    ->  {"notes": [ {id, text, author, created_at, updated_at}, ... ]}
Newest-first. No DB. Low-traffic single-writer use, so read-modify-write on the one blob is fine
(same posture as the registry itself).
"""
import os
import json
import time
import uuid

_PREFIX = "internal_notes"
MAX_TEXT_CHARS = 8000
MAX_NOTES = 500          # hard cap so the blob can never grow unbounded

_client = None


def _bucket():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client.bucket(os.environ["GCS_BUCKET"])


def _blob(client):
    return _bucket().blob(f"{_PREFIX}/{client}.json")


def _load(client):
    b = _blob(client)
    if not b.exists():
        return {"notes": []}
    try:
        doc = json.loads(b.download_as_bytes().decode("utf-8"))
    except Exception:
        return {"notes": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("notes"), list):
        return {"notes": []}
    return doc


def _save(client, doc):
    b = _blob(client)
    b.cache_control = "no-store"
    b.upload_from_string(json.dumps(doc, ensure_ascii=False), content_type="application/json")


def list_notes(client):
    """-> newest-first list of note dicts."""
    return _load(client)["notes"]


def add_note(client, text, author=""):
    """Prepend a note. Returns the stored record."""
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    if not text:
        raise ValueError("empty note")
    now = int(time.time())
    rec = {"id": f"{now}-{uuid.uuid4().hex[:8]}", "text": text,
           "author": (author or "").strip()[:120], "created_at": now, "updated_at": now}
    doc = _load(client)
    doc["notes"].insert(0, rec)
    del doc["notes"][MAX_NOTES:]
    _save(client, doc)
    return rec


def edit_note(client, note_id, text, author=""):
    """Replace a note's text (records the editor + updated_at). Returns the record or None."""
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    if not text:
        raise ValueError("empty note")
    doc = _load(client)
    for rec in doc["notes"]:
        if rec.get("id") == note_id:
            rec["text"] = text
            rec["updated_at"] = int(time.time())
            if author:
                rec["edited_by"] = (author or "").strip()[:120]
            _save(client, doc)
            return rec
    return None


def delete_note(client, note_id):
    """Remove a note. Returns True when something was deleted."""
    doc = _load(client)
    before = len(doc["notes"])
    doc["notes"] = [r for r in doc["notes"] if r.get("id") != note_id]
    if len(doc["notes"]) == before:
        return False
    _save(client, doc)
    return True
