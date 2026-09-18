"""kb_store.py - the knowledge base's storage layer. Plain GCS objects under `kb/`.

WHY GCS AND NOT A DATABASE. The corpus is thousands of chunks, not millions, and this service
already treats one private bucket as its trust boundary (the registry, feedback, internal notes).
A database would be a second thing to stand up, back up and pay for, to hold less data than the
feedback attachments already there.

THREE OBJECT KINDS, AND ONE OF THEM IS DENORMALISED ON PURPOSE:

    kb/docs/<doc_id>.json      the document: metadata + full text + revisions
    kb/chunks/<doc_id>.json    the retrievable passages + their vectors, WITH a small copy of the
                               document's metadata at the top
    kb/files/<doc_id>/<name>   the original upload, byte for byte

The `doc` header inside the chunks object is a deliberate duplication. The index rebuilds itself
by reading one object per document; without that header it would have to read `docs/` too, which
doubles the requests and drags every document's full body through a rebuild that only wants its
title and folder. Everything is written through `write_document` below, so the copy cannot drift
from the original - do not write either object by hand.

THE INDEX SIGNATURE IS THE LISTING, NOT `manifest.json`. A manifest is a mutable object that every
write has to read-modify-write, and Cloud Run runs several instances: two uploads landing together
lose an increment, and the instance that lost it never notices a document again. `list_blobs` over
`kb/chunks/` returns each object's name AND its generation, which is atomic by construction, needs
no coordination, and is exactly the per-document version number an incremental rebuild wants
anyway (kb_index.py). `manifest.json` survives only as a counts summary for the Observability
page, is written with a generation precondition, and is never the authority on freshness.

Object ids are validated on the way in (`_safe_id`), because they become path segments.
"""
import json
import os
import re
import time
import uuid

MAX_BODY_CHARS = 400_000        # the indexable ceiling; a cut is DECLARED, never silent
MAX_TITLE_CHARS = 300
MAX_FOLDER_CHARS = 200
MAX_REVISIONS = 40              # per document; the oldest fall off

# The prefix everything lives under. Overridable so a local verification run can use its own
# corner of the real bucket (KB_PREFIX=kb-dev) instead of writing into the live library.
PREFIX = os.environ.get("KB_PREFIX", "kb").strip("/") or "kb"

KINDS = ("note", "plan", "brief", "meeting", "reference", "feedback",
         "conversation")   # conversation: kb_slack.py - a Slack thread or channel-day (2026-09-17)
DEFAULT_KIND = "note"
SOURCES = ("upload", "paste", "assistant", "feedback", "fathom",    # fathom: kb_fathom.py (2026-09-15)
           "slack")                                                # slack: kb_slack.py (2026-09-17)
DEFAULT_SOURCE = "paste"
TRUST_VERIFIED = "verified"
TRUST_STANDARD = "standard"
TRUSTS = (TRUST_STANDARD, TRUST_VERIFIED)

# A document id is a path segment in three places, so it is generated here and validated on the
# way back in. Nothing outside this pattern may address an object.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")

_client = None


def _storage():
    global _client
    if _client is None:
        from google.cloud import storage
        _client = storage.Client()
    return _client


def bucket_name():
    return os.environ["GCS_BUCKET"]


def _bucket():
    return _storage().bucket(bucket_name())


def _blob(path):
    return _bucket().blob(f"{PREFIX}/{path}")


def _safe_id(doc_id):
    """The one gate on an id becoming a path segment. Raises rather than returning a default:
    a silently-rewritten id would read or write somebody else's document."""
    d = (doc_id or "").strip()
    if not _ID_RE.match(d):
        raise ValueError("bad document id")
    return d


def new_id():
    return "d_%d_%s" % (int(time.time()), uuid.uuid4().hex[:8])


def now():
    return int(time.time())


# --- low level ---------------------------------------------------------------------------------

def _read_json(path, default=None):
    b = _blob(path)
    try:
        raw = b.download_as_bytes()
    except Exception:                       # noqa: BLE001 - a missing object is not an error here
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:                       # noqa: BLE001 - a corrupt object degrades one document
        return default


def _write_json(path, obj, if_generation=None):
    """Write one JSON object. `if_generation` (0 for "must not exist") makes the write conditional,
    which is how a concurrent edit is detected rather than silently overwritten."""
    b = _blob(path)
    b.cache_control = "no-store"
    kw = {} if if_generation is None else {"if_generation_match": int(if_generation)}
    b.upload_from_string(json.dumps(obj, ensure_ascii=False), content_type="application/json", **kw)
    return b.generation


# --- documents ---------------------------------------------------------------------------------

def one_line(s, limit=MAX_TITLE_CHARS):
    """Collapse any run of whitespace, newlines included, to single spaces.

    🔴 A TITLE OR A FOLDER MAY NEVER CONTAIN A LINE BREAK. People paste, and a pasted title that
    still carries its newlines looks merely untidy in a list while doing real damage in the tree:
    a folder is a path STRING, so `Playbook\\n\\nBelow that we decline...` becomes a folder of that
    name, sitting in the rail forever, that nobody can explain. Caught in the first UI render.
    """
    return " ".join(str(s or "").split())[:limit]


def client_key(value):
    """A client registry key, cleaned. "" means agency-wide.

    Kept deliberately narrow (the same character set as a document id) because it becomes part of
    a scope comparison and, later, part of how a per-client dashboard asks for its own documents.
    Whether the key is one the registry KNOWS is checked at the route, where the session's own
    client list is available; this only guarantees the shape.
    """
    v = (value or "").strip().lower()
    return v if _KEY_RE.match(v) else ""


_KEY_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def normalize_folder(folder):
    """`Media plans/Q4` is `Q4` inside `Media plans`. Folders are a path convention over one flat
    string and there is no registry, so this is the only place the convention is enforced:
    segments whitespace-collapsed and trimmed, empties dropped, no leading or trailing slash, no
    `.` or `..`."""
    parts = []
    for seg in str(folder or "").replace("\\", "/").split("/"):
        s = one_line(seg, 80)
        if not s or s in (".", ".."):
            continue
        parts.append(s)
    return "/".join(parts)[:MAX_FOLDER_CHARS]


def doc_meta(doc):
    """The slice of a document that is NOT its text. This is what gets copied into the chunks
    object, and it is the ONLY definition of that slice.

    🔴 IT IS ALSO WHAT THE FILE LIST READS. Every row the Explorer draws comes from here, via the
    index's own cache, so listing a library of five hundred documents costs zero extra reads and
    never drags five hundred full bodies through the request. Anything a row or a search result
    needs belongs in this dict; anything else does not.
    """
    return {
        "id": doc["id"],
        "title": doc.get("title") or "",
        "folder": doc.get("folder") or "",
        # 🔴 WHICH CLIENT THIS IS ABOUT, as a registry KEY ("geocon"), or "" for agency-wide work
        # like the playbook. A FIELD, never a folder-name convention: this is the dimension the
        # retriever isolates on, and it is what will scope the library when it is dropped into a
        # single client's dashboard or into the Grid's client view. A convention encoded in a
        # string would be one rename away from leaking one client's plan into another's answer.
        "client": doc.get("client") or "",
        "kind": doc.get("kind") or DEFAULT_KIND,
        "source": doc.get("source") or DEFAULT_SOURCE,
        "trust": doc.get("trust") or TRUST_STANDARD,
        "archived": bool(doc.get("archived")),
        "owner": doc.get("owner") or "",
        "filename": doc.get("filename") or "",
        "mime": doc.get("mime") or "",
        "bytes": int(doc.get("bytes") or 0),
        "chars": len(doc.get("body") or ""),
        "created_at": doc.get("created_at") or 0,
        "updated_at": doc.get("updated_at") or 0,
        "updated_by": doc.get("updated_by") or "",
        # Empty when the vectors are built. Carried so a row can say "keyword only" on its face
        # rather than looking identical to a fully indexed document.
        "embed_error": doc.get("embed_error") or "",
        "revisions": len(doc.get("revisions") or []),
        # Passage ids this document CORRECTS. Carried on the meta so the retriever can demote a
        # superseded passage without reading any document body.
        "supersedes": list(doc.get("supersedes") or []),
        # The feedback record that produced this document, when one did.
        "feedback_id": doc.get("feedback_id") or "",
    }


def read_doc(doc_id, with_generation=False):
    """One document, or None. `with_generation` returns (doc, generation) so a caller can write it
    back conditionally and find out that somebody else edited it meanwhile."""
    d = _safe_id(doc_id)
    b = _blob(f"docs/{d}.json")
    try:
        raw = b.download_as_bytes()
    except Exception:                       # noqa: BLE001
        return (None, None) if with_generation else None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:                       # noqa: BLE001
        return (None, None) if with_generation else None
    return (doc, b.generation) if with_generation else doc


def write_doc(doc, if_generation=None):
    """Write the document object alone. Callers who change the TEXT should go through
    kb_index.reindex_document instead, so the chunks and the meta copy move with it."""
    d = _safe_id(doc.get("id"))
    return _write_json(f"docs/{d}.json", doc, if_generation=if_generation)


def make_doc(*, title="", body="", kind=None, folder="", source=DEFAULT_SOURCE, owner="",
             filename="", mime="", size_bytes=0, trust=TRUST_STANDARD, doc_id=None, client=""):
    """A new document object. Not written; hand it to kb_index.reindex_document."""
    ts = now()
    body = (body or "")[:MAX_BODY_CHARS]
    return {
        "id": _safe_id(doc_id) if doc_id else new_id(),
        "title": one_line(title) or title_from(body),
        "folder": normalize_folder(folder),
        "client": client_key(client),
        "kind": kind if kind in KINDS else DEFAULT_KIND,
        "source": source if source in SOURCES else DEFAULT_SOURCE,
        "filename": (filename or "")[:300],
        "mime": (mime or "")[:120],
        "bytes": int(size_bytes or 0),
        "body": body,
        "owner": (owner or "")[:200],
        "created_at": ts,
        "updated_at": ts,
        "updated_by": (owner or "")[:200],
        "indexed_at": 0,
        "indexed_hash": "",
        "embed_error": "",
        "trust": trust if trust in TRUSTS else TRUST_STANDARD,
        "archived": False,
        "supersedes": [],
        "revisions": [],
    }


def title_from(body):
    """A first line to name an untitled paste. A library full of "Untitled" is a library nobody
    searches."""
    for line in (body or "").splitlines():
        t = one_line(line.lstrip("#"), 120)
        if t:
            return t
    return "Untitled"


def push_revision(doc, *, by="", via="human", note=""):
    """Snapshot the document as it is NOW, before a change lands. The newest revision is always
    the state prior to the most recent edit, which is what "restore the previous version" has to
    mean. Full bodies, not diffs: documents are kilobytes and a diff chain that cannot be replayed
    without every link is the worse trade."""
    doc.setdefault("revisions", []).insert(0, {
        "at": now(), "by": (by or "")[:200],
        "via": via if via in ("human", "assistant") else "human",
        "note": (note or "")[:300],
        "title": doc.get("title") or "", "body": doc.get("body") or "",
    })
    del doc["revisions"][MAX_REVISIONS:]
    return doc


def delete_doc(doc_id):
    """Remove a document and everything that belongs to it. Returns True when the document existed."""
    d = _safe_id(doc_id)
    existed = _blob(f"docs/{d}.json").exists()
    for path in (f"docs/{d}.json", f"chunks/{d}.json"):
        try:
            _blob(path).delete()
        except Exception:                   # noqa: BLE001 - already gone is the desired state
            pass
    for b in _storage().list_blobs(bucket_name(), prefix=f"{PREFIX}/files/{d}/"):
        try:
            b.delete()
        except Exception:                   # noqa: BLE001
            pass
    return existed


def list_doc_ids():
    """Every document id that has a `docs/` object, archived ones included."""
    out = []
    n = len(f"{PREFIX}/docs/")
    for b in _storage().list_blobs(bucket_name(), prefix=f"{PREFIX}/docs/"):
        name = b.name[n:]
        if name.endswith(".json"):
            out.append(name[:-5])
    return sorted(out)


# --- chunks ------------------------------------------------------------------------------------

def write_chunks(doc, chunks, model=""):
    """The retrievable form of one document: its passages, their vectors, and the copy of its
    metadata the index reads. `chunks` = [{ord, text, embedding}]."""
    d = _safe_id(doc["id"])
    return _write_json(f"chunks/{d}.json",
                       {"doc": doc_meta(doc), "model": model or "", "written_at": now(),
                        "chunks": chunks})


def read_chunks(doc_id):
    """-> {doc, model, written_at, chunks[]} or None."""
    obj = _read_json(f"chunks/{_safe_id(doc_id)}.json")
    if not isinstance(obj, dict) or not isinstance(obj.get("chunks"), list):
        return None
    return obj


def read_chunks_by_name(name):
    """Read a chunks object by its FULL blob name, as `chunk_signature` reports it. Used by the
    incremental rebuild, which already holds the listing and must not recompute the path."""
    b = _bucket().blob(name)
    try:
        raw = b.download_as_bytes()
    except Exception:                       # noqa: BLE001
        return None
    try:
        obj = json.loads(raw.decode("utf-8"))
    except Exception:                       # noqa: BLE001
        return None
    return obj if isinstance(obj, dict) and isinstance(obj.get("chunks"), list) else None


def chunk_signature():
    """(doc_id, blob_name, generation) for every chunks object, sorted by id.

    🔴 THIS IS THE INDEX'S FRESHNESS SIGNAL, and the reason there is no manifest in the hot path.
    A GCS generation changes on every write and on nothing else, so a corpus built from a given
    set of generations is provably current or provably not, with no counter for two instances to
    race over. It also IS the per-document version an incremental rebuild needs, so the check and
    the diff are one call.
    """
    out = []
    n = len(f"{PREFIX}/chunks/")
    for b in _storage().list_blobs(bucket_name(), prefix=f"{PREFIX}/chunks/"):
        name = b.name[n:]
        if name.endswith(".json"):
            out.append((name[:-5], b.name, int(b.generation)))
    out.sort()
    return out


# --- original files ----------------------------------------------------------------------------

def write_file(doc_id, filename, data, content_type=""):
    """Keep the upload as it arrived. Sentinel discards the file and keeps only the text; here a
    media plan gets re-opened by a human, so both are kept and the text is what is searched."""
    d = _safe_id(doc_id)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", (filename or "file").strip())[:200] or "file"
    b = _blob(f"files/{d}/{safe}")
    b.cache_control = "no-store"
    b.upload_from_string(data, content_type=content_type or "application/octet-stream")
    return safe


def read_file(doc_id, filename):
    """-> (bytes, content_type) or (None, None)."""
    d = _safe_id(doc_id)
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", (filename or "").strip())[:200]
    if not safe:
        return None, None
    b = _blob(f"files/{d}/{safe}")
    try:
        data = b.download_as_bytes()
    except Exception:                       # noqa: BLE001
        return None, None
    return data, (b.content_type or "application/octet-stream")


# --- conversations -------------------------------------------------------------------------------
# kb/chats/<actor_key>/<conv_id>.json
#
# 🔴 "PRIVATE TO THAT USER" IS ONLY TRUE FOR AN EMAIL SIGN-IN. A typed admin password and the
# shared agency password identify a TIER, not a person, so every holder of that password shares one
# actor key and therefore one set of conversations. That is a property of how the platform
# authenticates, not something this store can fix, so the UI states it rather than implying a
# privacy that does not exist. Do not "improve" this by inventing a per-browser id: a conversation
# that quietly disappears when somebody clears their cookies is worse than a shared one they were
# told about.

def display_actor(actor):
    """An actor string as a person should read it.

    🔴 THE RAW STRING MUST NOT REACH A SENTENCE. `_kb_actor` records `shared:superadmin` for a typed
    password, and the assistant, told to name who made a correction, dutifully wrote "this follows a
    correction shared:superadmin made". Honest and unreadable. Caught on the first live turn.
    """
    a = (actor or "").strip()
    if not a:
        return "somebody"
    if a.startswith("shared:"):
        return "%s (shared login)" % a[7:]
    if a.startswith("agency:"):
        return "%s (shared login)" % a[7:]
    return a


def actor_key(actor):
    """An actor string into one safe path segment. A readable slug plus a hash, so a key is both
    debuggable in a bucket listing and impossible to collide or escape with."""
    import hashlib
    a = (actor or "anon").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", a).strip("-")[:40] or "anon"
    return "%s-%s" % (slug, hashlib.sha1(a.encode("utf-8")).hexdigest()[:8])


def new_conv_id():
    return "c_%d_%s" % (int(time.time()), uuid.uuid4().hex[:8])


def read_chat(actor, conv_id):
    if not _ID_RE.match(conv_id or ""):
        return None
    return _read_json(f"chats/{actor_key(actor)}/{conv_id}.json")


def write_chat(actor, conv):
    conv["updated_at"] = now()
    _write_json(f"chats/{actor_key(actor)}/{conv['id']}.json", conv)
    return conv


def list_chats(actor, limit=40):
    """Newest first, titles only. The object name carries the timestamp, so the listing sorts
    without reading anything."""
    base = f"{PREFIX}/chats/{actor_key(actor)}/"
    names = sorted((b.name for b in _storage().list_blobs(bucket_name(), prefix=base)
                    if b.name.endswith(".json")), reverse=True)[:limit]
    out = []
    for n in names:
        doc = _read_json(n[len(PREFIX) + 1:])
        if isinstance(doc, dict):
            out.append({"id": doc.get("id"), "title": doc.get("title") or "Untitled",
                        "updated_at": doc.get("updated_at") or 0,
                        "turns": len(doc.get("messages") or [])})
    return out


def delete_chat(actor, conv_id):
    if not _ID_RE.match(conv_id or ""):
        return False
    try:
        _blob(f"chats/{actor_key(actor)}/{conv_id}.json").delete()
        return True
    except Exception:                       # noqa: BLE001
        return False


# --- feedback -------------------------------------------------------------------------------------

def write_feedback(rec):
    _write_json(f"feedback/{rec['id']}.json", rec)
    return rec


def read_feedback(fb_id):
    if not _ID_RE.match(fb_id or ""):
        return None
    return _read_json(f"feedback/{fb_id}.json")


def list_feedback(limit=300):
    base = f"{PREFIX}/feedback/"
    names = sorted((b.name for b in _storage().list_blobs(bucket_name(), prefix=base)
                    if b.name.endswith(".json")), reverse=True)[:limit]
    out = []
    for n in names:
        doc = _read_json(n[len(PREFIX) + 1:])
        if isinstance(doc, dict):
            out.append(doc)
    return out


def new_feedback_id():
    return "f_%d_%s" % (int(time.time()), uuid.uuid4().hex[:8])


# --- manifest (a SUMMARY, never the authority - see the module header) --------------------------

def read_manifest():
    m = _read_json("manifest.json", default=None)
    if not isinstance(m, dict):
        return {"generation": 0, "docs": 0, "chunks": 0, "embedded": 0, "updated_at": 0}
    return m


def write_manifest(docs, chunks, embedded):
    """Best effort, and deliberately so. It feeds the Observability page's counts; nothing about
    retrieval depends on it, so a lost race here costs a stale number on one panel and never a
    document that stops being searchable."""
    for _ in range(3):
        b = _blob("manifest.json")
        try:
            cur = json.loads(b.download_as_bytes().decode("utf-8"))
            gen = b.generation
        except Exception:                   # noqa: BLE001
            cur, gen = {}, 0
        doc = {"generation": int(cur.get("generation") or 0) + 1, "docs": int(docs),
               "chunks": int(chunks), "embedded": int(embedded), "updated_at": now()}
        try:
            _write_json("manifest.json", doc, if_generation=gen)
            return doc
        except Exception:                   # noqa: BLE001 - somebody else wrote it; re-read and retry
            continue
    return None
