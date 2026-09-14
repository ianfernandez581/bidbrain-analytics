"""kb_routes.py - every HTTP surface of the knowledge base, as one blueprint.

🔴 THE ROUTE IS THE GATE. A template flag decides what RENDERS; it never decides what a person may
fetch. Every route here calls `_deny()` first, and the predicate behind it lives in main.py
(`_kb_allowed`) next to the other session gates, so there is one place that answers "may this
session touch the knowledge base".

🔴 THE BLUEPRINT'S ENDPOINTS ARE NOT IN `_EXTERNAL_ALLOWED_ENDPOINTS`, WHICH IS THE POINT. main.py
denies an external agency every endpoint it has not explicitly allowed, so a route added here is
closed to outside tenants by construction rather than by somebody remembering. Do not add `kb.*`
to that set.

The gate functions arrive through `init()` rather than by importing main, because main imports this
module. No circular import, and the seam is explicit.
"""
import json
import logging
import time

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request

import kb_chat
import kb_extract
import kb_feedback
import kb_index
import kb_prompt
import kb_store

log = logging.getLogger(__name__)

bp = Blueprint("kb", __name__, url_prefix="/kb")

# Injected by init(). Module-level rather than a factory so the route decorators stay readable.
_allowed = None          # () -> bool: may this session use the knowledge base at all
_signed_in = None        # () -> bool: is there any session (else a page route sends them to login)
_actor = None            # () -> str: who to record as an author
_blocked = None          # (what) -> response | None: the local-run production write guard
_page_ctx = None         # () -> dict: logo, whether this session is staff, whether it is shared

# The folders the library starts with, each with a one line note saying what belongs there. Seeded
# once, only into an EMPTY library, so nobody's own structure is ever overwritten.
SEED_FOLDERS = [
    ("Media plans", "Signed media plans and the briefs they were bought against. One document per "
                    "plan, named for the campaign and the quarter."),
    ("Briefs", "Client briefs as they arrived, before we interpreted them. Keep the original "
               "wording: what a client asked for is evidence, not a draft."),
    ("Meetings", "What was decided and by whom. Outcomes, not transcripts."),
    ("Platform docs", "How the dashboards, the pipelines and the reporting actually work."),
    ("Playbook", "How we do the work: process, standards, the reasoning behind a rule."),
    ("Media buyer knowledge", "Corrections buyers have made to the assistant's answers. These are "
                              "trusted: an answer that leans on one says so. Written by the "
                              "feedback loop, and by hand when somebody knows something the "
                              "library does not."),
]


def init(app, *, allowed, signed_in, actor, mutation_blocked, page_context):
    global _allowed, _signed_in, _actor, _blocked, _page_ctx
    _allowed, _signed_in, _actor, _blocked = allowed, signed_in, actor, mutation_blocked
    _page_ctx = page_context
    app.register_blueprint(bp)


# --- gates ---------------------------------------------------------------------------------------

def _deny():
    """None when this session may proceed, else the response to return. API routes get JSON so the
    UI can tell an auth failure from a policy refusal (see the repo rule on never reporting an auth
    failure as "try again")."""
    if not _signed_in():
        return jsonify(ok=False, error="Sign in to use the knowledge base.", reason="auth"), 401
    if not _allowed():
        return jsonify(ok=False, error="The knowledge base is not available for this account.",
                       reason="forbidden"), 403
    return None


def _deny_page():
    if not _signed_in():
        return redirect("/")
    if not _allowed():
        abort(403)
    return None


def _guard_write(what):
    """The local-run production write guard, plus the write gate. Returns a response or None."""
    d = _deny()
    if d:
        return d
    return _blocked(what)


def _json():
    return request.get_json(silent=True) or {}


# --- pages ---------------------------------------------------------------------------------------

@bp.get("/")
def documents_page():
    d = _deny_page()
    if d:
        return d
    return render_template("kb_documents.html", actor=_actor(),
                           kinds=list(kb_store.KINDS), page="documents", **_page_ctx())


@bp.get("/observability")
def observability_page():
    """🔴 STAFF ONLY, per the access table: a 100% Digital session may use the library and correct
    it, but the page that shows every question anybody has asked is ours. The route is the gate; the
    nav link is merely hidden."""
    d = _deny_page()
    if d:
        return d
    if not _page_ctx().get("is_staff"):
        abort(403)
    return render_template("kb_observability.html", actor=_actor(), page="observability",
                           **_page_ctx())


def _deny_staff():
    d = _deny()
    if d:
        return d
    if not _page_ctx().get("is_staff"):
        return jsonify(ok=False, error="Observability is staff only.", reason="forbidden"), 403
    return None


# --- the library -----------------------------------------------------------------------------

def _seed_if_empty():
    """Create the starting folders, once, and only into a library with nothing in it. Each is a
    real document (a folder with no documents does not exist here), so the note explaining what
    belongs in a folder is itself searchable."""
    if kb_index.all_meta():
        return 0
    made = 0
    for folder, blurb in SEED_FOLDERS:
        doc = kb_store.make_doc(title="About this folder: %s" % folder,
                                body="%s\n\n%s\n" % (folder, blurb),
                                folder=folder, kind="reference", source="paste",
                                owner="bidbrain")
        kb_index.reindex_document(doc)
        made += 1
    log.info("kb: seeded %d starting folder(s)", made)
    return made


@bp.get("/tree")
def tree():
    d = _deny()
    if d:
        return d
    if request.args.get("seed") == "1":
        b = _blocked("kb seed")
        if b:
            return b
        _seed_if_empty()
    counts = kb_index.folder_counts()
    meta = kb_index.all_meta()
    paths = sorted([p for p in counts if p != kb_index.ROOT_FOLDER], key=str.lower)
    return jsonify(ok=True,
                   folders=[{"path": p, "name": p.split("/")[-1], "depth": p.count("/"),
                             "count": counts[p]} for p in paths],
                   root_count=counts.get(kb_index.ROOT_FOLDER, 0),
                   total=sum(1 for m in meta.values() if not m.get("archived")),
                   archived=sum(1 for m in meta.values() if m.get("archived")),
                   empty=not meta)


def _row(meta):
    """One file-list row. Derived, never stored: a status field would be a fourth thing to keep in
    step with the three that already say this."""
    chunks, embedded = int(meta.get("chunks") or 0), int(meta.get("embedded") or 0)
    if meta.get("embed_error"):
        state, note = "keyword", meta["embed_error"]
    elif chunks and not embedded:
        state, note = "indexing", "building meaning search for this document"
    elif not chunks:
        state, note = "empty", "no text to search"
    else:
        state, note = "searchable", ""
    out = {k: meta.get(k) for k in ("id", "title", "folder", "kind", "source", "trust", "archived",
                                    "owner", "filename", "mime", "bytes", "chars", "created_at",
                                    "updated_at", "updated_by", "revisions", "feedback_id")}
    out.update(chunks=chunks, embedded=embedded, state=state, state_note=note)
    return out


@bp.get("/docs")
def list_docs():
    d = _deny()
    if d:
        return d
    folder = request.args.get("folder", "")
    deep = request.args.get("deep") == "1"
    want_archived = request.args.get("archived") == "1"
    q = (request.args.get("q") or "").strip().lower()
    rows = []
    for meta in kb_index.all_meta().values():
        if bool(meta.get("archived")) != want_archived:
            continue
        f = meta.get("folder") or ""
        if folder == kb_index.ROOT_FOLDER:
            if f:
                continue
        elif folder:
            norm = kb_store.normalize_folder(folder)
            if not (f == norm or (deep and f.startswith(norm + "/"))):
                continue
        if q and q not in (meta.get("title") or "").lower() \
                and q not in (meta.get("filename") or "").lower():
            continue
        rows.append(_row(meta))
    rows.sort(key=lambda r: (r["title"] or "").lower())
    return jsonify(ok=True, docs=rows, folder=folder)


@bp.get("/docs/<doc_id>")
def get_doc(doc_id):
    d = _deny()
    if d:
        return d
    try:
        doc, gen = kb_store.read_doc(doc_id, with_generation=True)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    if not doc:
        return jsonify(ok=False, error="No such document."), 404
    chunks = kb_store.read_chunks(doc_id) or {"chunks": []}
    meta = dict(kb_store.doc_meta(doc))
    meta["chunks"] = len(chunks["chunks"])
    meta["embedded"] = sum(1 for c in chunks["chunks"] if c.get("embedding"))
    return jsonify(ok=True, doc={**_row(meta), "body": doc.get("body") or "",
                                 "supersedes": doc.get("supersedes") or [],
                                 "indexed_at": doc.get("indexed_at") or 0,
                                 "generation": gen,
                                 "revision_list": [
                                     {"at": r.get("at"), "by": r.get("by"), "via": r.get("via"),
                                      "note": r.get("note"), "title": r.get("title")}
                                     for r in (doc.get("revisions") or [])]},
                   passages=[{"ord": c.get("ord"), "text": c.get("text"),
                              "embedded": bool(c.get("embedding"))}
                             for c in chunks["chunks"]])


@bp.post("/docs")
def create_doc():
    g = _guard_write("kb create document")
    if g:
        return g
    j = _json()
    body = str(j.get("body") or "")
    title = str(j.get("title") or "").strip()
    if not title and not body.strip():
        return jsonify(ok=False, error="A document needs a title or some text."), 400
    doc = kb_store.make_doc(title=title, body=body, folder=j.get("folder") or "",
                            kind=j.get("kind"), source="paste", owner=_actor())
    rep = kb_index.reindex_document(doc)
    _log_event("doc_added", doc_id=doc["id"], title=doc["title"], folder=doc["folder"],
               chunks=rep["chunks"], semantic=rep["semantic"])
    return jsonify(ok=True, doc=_row({**kb_store.doc_meta(doc), "chunks": rep["chunks"],
                                      "embedded": rep["chunks"] if rep["semantic"] else 0}),
                   index=rep)


@bp.post("/upload")
def upload():
    g = _guard_write("kb upload")
    if g:
        return g
    folder = request.form.get("folder") or ""
    files = request.files.getlist("file")
    if not files:
        return jsonify(ok=False, error="No file was sent."), 400
    made, failed = [], []
    for f in files:
        data = f.read()
        try:
            got = kb_extract.extract(f.filename, data, mime=f.mimetype or "")
        except kb_extract.ExtractError as e:
            # 🔴 Refused, not stored. See kb_extract's header on why mojibake is the worse outcome.
            failed.append({"filename": f.filename, "error": str(e)})
            continue
        doc = kb_store.make_doc(title=kb_extract.title_for(f.filename, got["text"]),
                                body=got["text"], folder=folder, kind=got["kind_hint"],
                                source="upload", owner=_actor(), filename=f.filename,
                                mime=f.mimetype or "", size_bytes=len(data))
        # The original first: if indexing fails, the file a person uploaded is still there.
        try:
            doc["filename"] = kb_store.write_file(doc["id"], f.filename, data,
                                                  content_type=f.mimetype or "")
        except Exception:                          # noqa: BLE001 - the text is the searchable part
            log.exception("kb: could not keep the original of %s", f.filename)
        rep = kb_index.reindex_document(doc)
        _log_event("doc_added", doc_id=doc["id"], title=doc["title"], folder=doc["folder"],
                   chunks=rep["chunks"], semantic=rep["semantic"], source="upload")
        made.append(_row({**kb_store.doc_meta(doc), "chunks": rep["chunks"],
                          "embedded": rep["chunks"] if rep["semantic"] else 0}))
        if got["note"]:
            made[-1]["import_note"] = got["note"]
    status = 200 if made else 400
    return jsonify(ok=bool(made), docs=made, failed=failed), status


@bp.route("/docs/<doc_id>", methods=["PATCH"])
def patch_doc(doc_id):
    g = _guard_write("kb edit document")
    if g:
        return g
    j = _json()
    try:
        doc, gen = kb_store.read_doc(doc_id, with_generation=True)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    if not doc:
        return jsonify(ok=False, error="No such document."), 404
    # A concurrent edit is DETECTED, not silently won. The Explorer sends back the generation it
    # read; a caller that sends none is trusted (the assistant's own writes go through here too).
    seen = j.get("generation")
    if seen is not None and int(seen) != int(gen or 0):
        return jsonify(ok=False, error="Somebody else changed this document while you had it open. "
                                       "Reload to see their version.", reason="conflict"), 409

    title = j.get("title")
    body = j.get("body")
    text_changed = ((title is not None and kb_store.one_line(title) != doc["title"])
                    or (body is not None and str(body)[:kb_store.MAX_BODY_CHARS] != doc.get("body")))
    if text_changed:
        kb_store.push_revision(doc, by=_actor(), via=j.get("via") or "human",
                               note=str(j.get("note") or "")[:300])
    if title is not None:
        doc["title"] = kb_store.one_line(title) or doc["title"]
    if body is not None:
        doc["body"] = str(body)[:kb_store.MAX_BODY_CHARS]
    if j.get("kind") in kb_store.KINDS:
        doc["kind"] = j["kind"]
    if j.get("folder") is not None:
        doc["folder"] = kb_store.normalize_folder(j["folder"])
    if j.get("trust") in kb_store.TRUSTS:
        doc["trust"] = j["trust"]
    if j.get("archived") is not None:
        doc["archived"] = bool(j["archived"])
    doc["updated_at"] = kb_store.now()
    doc["updated_by"] = _actor()
    rep = kb_index.reindex_document(doc, force=text_changed)
    _log_event("doc_edited", doc_id=doc["id"], title=doc["title"], text_changed=text_changed)
    return jsonify(ok=True, doc=_row({**kb_store.doc_meta(doc), "chunks": rep["chunks"],
                                      "embedded": rep["chunks"] if rep["semantic"] else 0}))


@bp.route("/docs/<doc_id>", methods=["DELETE"])
def delete_doc(doc_id):
    g = _guard_write("kb delete document")
    if g:
        return g
    try:
        existed = kb_store.delete_doc(doc_id)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    kb_index.invalidate()
    if existed:
        _log_event("doc_deleted", doc_id=doc_id)
    return (jsonify(ok=True) if existed else (jsonify(ok=False, error="No such document."), 404))


@bp.post("/docs/<doc_id>/move")
def move_doc(doc_id):
    g = _guard_write("kb move document")
    if g:
        return g
    try:
        doc = kb_store.read_doc(doc_id)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    if not doc:
        return jsonify(ok=False, error="No such document."), 404
    doc["folder"] = kb_store.normalize_folder(_json().get("folder") or "")
    doc["updated_at"] = kb_store.now()
    doc["updated_by"] = _actor()
    # Moving changes no text, so the passages stand; the copy of the metadata inside the chunks
    # object does not, and the index reads that copy.
    chunks = kb_store.read_chunks(doc_id) or {"chunks": [], "model": ""}
    kb_store.write_chunks(doc, chunks["chunks"], model=chunks.get("model") or "")
    kb_store.write_doc(doc)
    kb_index.invalidate()
    _log_event("doc_moved", doc_id=doc_id, folder=doc["folder"])
    return jsonify(ok=True, folder=doc["folder"])


@bp.post("/docs/<doc_id>/restore")
def restore_revision(doc_id):
    g = _guard_write("kb restore revision")
    if g:
        return g
    try:
        doc = kb_store.read_doc(doc_id)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    if not doc:
        return jsonify(ok=False, error="No such document."), 404
    revs = doc.get("revisions") or []
    i = int(_json().get("index") or 0)
    if i < 0 or i >= len(revs):
        return jsonify(ok=False, error="No such version."), 404
    rev = revs[i]
    # Restoring is itself an edit, so the state being replaced is kept too and history never loses
    # a branch.
    kb_store.push_revision(doc, by=_actor(), note="Restored an earlier version")
    doc["title"] = rev.get("title") or doc["title"]
    doc["body"] = rev.get("body") or ""
    doc["updated_at"] = kb_store.now()
    doc["updated_by"] = _actor()
    kb_index.reindex_document(doc, force=True)
    _log_event("doc_edited", doc_id=doc_id, title=doc["title"], restored=True)
    return jsonify(ok=True)


@bp.get("/file/<doc_id>")
def get_file(doc_id):
    d = _deny()
    if d:
        return d
    try:
        doc = kb_store.read_doc(doc_id)
    except ValueError:
        return jsonify(ok=False, error="bad id"), 400
    if not doc or not doc.get("filename"):
        return jsonify(ok=False, error="That document has no original file."), 404
    data, ctype = kb_store.read_file(doc_id, doc["filename"])
    if data is None:
        return jsonify(ok=False, error="The original file is missing."), 404
    name = doc["filename"].replace('"', "")
    return Response(data, mimetype=ctype,
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})


# --- folders (a convention, so these are bulk edits over the documents beneath a path) -----------

@bp.post("/folder/rename")
def rename_folder():
    g = _guard_write("kb rename folder")
    if g:
        return g
    j = _json()
    src = kb_store.normalize_folder(j.get("from") or "")
    dst = kb_store.normalize_folder(j.get("to") or "")
    if not src or not dst:
        return jsonify(ok=False, error="A folder needs a name."), 400
    if dst == src:
        return jsonify(ok=True, moved=0)
    if dst.startswith(src + "/"):
        return jsonify(ok=False, error="A folder cannot be moved inside itself."), 400
    moved = 0
    for meta in list(kb_index.all_meta().values()):
        f = meta.get("folder") or ""
        if f != src and not f.startswith(src + "/"):
            continue
        doc = kb_store.read_doc(meta["id"])
        if not doc:
            continue
        doc["folder"] = dst + f[len(src):]
        doc["updated_at"] = kb_store.now()
        doc["updated_by"] = _actor()
        chunks = kb_store.read_chunks(meta["id"]) or {"chunks": [], "model": ""}
        kb_store.write_chunks(doc, chunks["chunks"], model=chunks.get("model") or "")
        kb_store.write_doc(doc)
        moved += 1
    kb_index.invalidate()
    _log_event("folder_renamed", folder=src, to=dst, moved=moved)
    return jsonify(ok=True, moved=moved, folder=dst)


@bp.post("/folder/delete")
def delete_folder():
    g = _guard_write("kb delete folder")
    if g:
        return g
    path = kb_store.normalize_folder(_json().get("path") or "")
    if not path:
        return jsonify(ok=False, error="Which folder?"), 400
    inside = [m for m in kb_index.all_meta().values()
              if (m.get("folder") or "") == path or (m.get("folder") or "").startswith(path + "/")]
    if inside:
        # A folder here is not a thing that can be empty: it exists because documents are in it.
        # Deleting one would therefore mean deleting them, which is never what a click meant.
        return jsonify(ok=False, count=len(inside),
                       error="That folder still holds %d document%s. Move or delete them first."
                             % (len(inside), "" if len(inside) == 1 else "s")), 409
    return jsonify(ok=True, moved=0)


# --- retrieval -------------------------------------------------------------------------------

@bp.post("/search")
def search():
    d = _deny()
    if d:
        return d
    j = _json()
    q = str(j.get("q") or "")
    res = kb_index.search(q, limit=int(j.get("limit") or kb_index.DEFAULT_LIMIT),
                          folders=j.get("folders") or None, strict=bool(j.get("strict")))
    # `docs` is what makes "which documents are never retrieved" answerable later. Ids only: the
    # passage text stays in the library, never in the usage record.
    _log_event("search", query=q[:300], scope=res["scope"], passages=len(res["excerpts"]),
               semantic=res["semantic"], ms=res["ms"], outcome=res["outcome"],
               docs=sorted({e["document_id"] for e in res["excerpts"]}))
    return jsonify(ok=True, **res)


@bp.get("/status")
def index_status():
    d = _deny()
    if d:
        return d
    import kb_embed
    st = kb_index.status()
    return jsonify(ok=True, index=st, manifest=kb_store.read_manifest(),
                   embeddings={"enabled": kb_embed.enabled(), "model": kb_embed.model_name(),
                               "region": kb_embed.location()},
                   prefix=kb_store.PREFIX, bucket=kb_store.bucket_name())


# --- the assistant -------------------------------------------------------------------------------

def _sse(event, data):
    return "event: %s\ndata: %s\n\n" % (event, json.dumps(data, ensure_ascii=False))


@bp.post("/ask")
def ask():
    """One answer, streamed.

    🔴 EVERYTHING THE GENERATOR NEEDS IS CAPTURED BEFORE IT STARTS. A Flask generator outlives the
    request context, so reading `session` or `request` inside it is a runtime error that only shows
    up under load. Actor, scope and question are read here, once.

    🔴 RETRIEVAL IS SENT BEFORE THE FIRST TOKEN. The citations render while the model is still
    writing, so a reader can see WHAT it is answering from before they see the answer, which is the
    difference between a cited answer and one that merely has references appended.
    """
    d = _deny()
    if d:
        return d
    j = _json()
    question = str(j.get("q") or "").strip()
    if not question:
        return jsonify(ok=False, error="Ask something."), 400
    folders = j.get("folders") or None
    conv_id = str(j.get("conv_id") or "").strip()
    actor = _actor()

    conv = kb_store.read_chat(actor, conv_id) if conv_id else None
    if not conv:
        conv = {"id": kb_store.new_conv_id(), "title": question[:120],
                "created_at": kb_store.now(), "messages": []}
    history = list(conv.get("messages") or [])

    def gen():
        started = time.time()
        try:
            res = kb_index.search(question, folders=folders, strict=True)
        except Exception:                          # noqa: BLE001
            log.exception("kb: retrieval failed")
            yield _sse("error", {"message": "The library could not be searched just now. Nothing "
                                            "was lost; try the question again in a moment."})
            return
        yield _sse("retrieval", {
            "excerpts": [{k: e[k] for k in ("document_id", "title", "folder", "trust", "ord",
                                            "passage_id", "passage", "found_by", "score",
                                            "keyword_rank", "semantic_rank", "semantic_score")}
                         for e in res["excerpts"]],
            "semantic": res["semantic"], "semantic_error": res["semantic_error"],
            "scope": res["scope"], "outcome": res["outcome"],
            "documents_searched": res["documents_searched"],
            "unembedded_documents": res["unembedded_documents"], "ms": res["ms"],
        })

        prefix = kb_prompt.prefix(res["excerpts"], semantic=res["semantic"],
                                  semantic_error=res["semantic_error"], scope=res["scope"],
                                  unembedded=res["unembedded_documents"])
        messages = kb_prompt.turns(history, question)
        answer, model_info, usage = [], None, {}
        try:
            for kind, payload in kb_chat.stream(prefix, messages):
                if kind == "model":
                    model_info = payload
                    yield _sse("model", payload)
                elif kind == "token":
                    answer.append(payload)
                    yield _sse("token", {"t": payload})
                elif kind == "usage":
                    usage = payload
        except kb_chat.ProviderError as exc:
            log.warning("kb: no model answered: %s", exc)
            yield _sse("error", {
                "message": ("No model could answer just now (%s). The passages above are the real "
                            "search result and are still correct." % exc),
                "retrieval_ok": True})
            return
        text = "".join(answer).strip()
        turn_id = "a_%d" % int(time.time() * 1000)
        conv["messages"] = history + [
            {"role": "user", "content": question, "at": kb_store.now()},
            {"role": "assistant", "content": text, "at": kb_store.now(), "id": turn_id,
             "model": (model_info or {}).get("model", ""),
             "provider": (model_info or {}).get("provider", ""),
             "semantic": res["semantic"], "scope": res["scope"],
             "passages": [e["passage_id"] for e in res["excerpts"]]},
        ][-60:]
        try:
            kb_store.write_chat(actor, conv)
        except Exception:                          # noqa: BLE001 - never lose the answer over this
            log.exception("kb: could not save the conversation")
        ms = int((time.time() - started) * 1000)
        _log_event("question", query=question[:300], scope=res["scope"],
                   passages=len(res["excerpts"]), semantic=res["semantic"], ms=ms,
                   model=(model_info or {}).get("model", ""),
                   provider=(model_info or {}).get("provider", ""),
                   fallback=bool((model_info or {}).get("fallback")),
                   docs=sorted({e["document_id"] for e in res["excerpts"]}),
                   outcome=res["outcome"], tokens_out=usage.get("tokens_out"),
                   conv_id=conv["id"], answer_id=turn_id)
        yield _sse("done", {"conv_id": conv["id"], "answer_id": turn_id, "ms": ms,
                            "usage": usage, "title": conv["title"]})

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@bp.get("/chats")
def list_chats():
    d = _deny()
    if d:
        return d
    return jsonify(ok=True, chats=kb_store.list_chats(_actor()), shared=_shared_login())


@bp.get("/chats/<conv_id>")
def get_chat(conv_id):
    d = _deny()
    if d:
        return d
    conv = kb_store.read_chat(_actor(), conv_id)
    if not conv:
        return jsonify(ok=False, error="No such conversation."), 404
    return jsonify(ok=True, chat=conv)


@bp.route("/chats/<conv_id>", methods=["DELETE"])
def delete_chat(conv_id):
    g = _guard_write("kb delete conversation")
    if g:
        return g
    return jsonify(ok=kb_store.delete_chat(_actor(), conv_id))


# --- the feedback loop ---------------------------------------------------------------------------

@bp.post("/feedback")
def feedback():
    g = _guard_write("kb feedback")
    if g:
        return g
    j = _json()
    try:
        rec = kb_feedback.submit(
            question=j.get("question"), answer=j.get("answer"), verdict=j.get("verdict"),
            rule=j.get("rule"), correction=j.get("correction"),
            cited=j.get("cited") or [], superseded=j.get("superseded") or [],
            actor=_actor(), model=j.get("model") or "", conv_id=j.get("conv_id") or "",
            answer_id=j.get("answer_id") or "", scope=j.get("scope") or [],
            semantic=bool(j.get("semantic", True)))
    except Exception:                              # noqa: BLE001
        log.exception("kb: feedback failed")
        return jsonify(ok=False, error="That could not be saved. Your words are still in the box; "
                                       "try again in a moment."), 500
    _log_event("feedback", verdict=rec["verdict"], promoted=bool(rec["doc_id"]),
               doc_id=rec["doc_id"], superseded=len(rec["superseded"]),
               query=(rec["question"] or "")[:300])
    return jsonify(ok=True, feedback=rec)


@bp.get("/feedback")
def feedback_list():
    d = _deny()
    if d:
        return d
    rows = kb_feedback.recent()
    return jsonify(ok=True, feedback=rows, summary=kb_feedback.summary(rows), me=_actor())


@bp.post("/feedback/<fb_id>/withdraw")
def feedback_withdraw(fb_id):
    g = _guard_write("kb withdraw feedback")
    if g:
        return g
    rec, err = kb_feedback.withdraw(fb_id, _actor(),
                                    is_staff=bool(_page_ctx().get("is_staff")))
    if not rec:
        return jsonify(ok=False, error=err), 404 if "No such" in err else 403
    return jsonify(ok=True, feedback=rec)


def _shared_login():
    try:
        return bool(_page_ctx().get("shared_login"))
    except Exception:                              # noqa: BLE001
        return False


# --- observability -------------------------------------------------------------------------------

@bp.get("/obs/data")
def obs_data():
    d = _deny_staff()
    if d:
        return d
    import kb_activity
    import kb_embed
    import kb_trace
    meta = kb_index.all_meta(include_archived=False)
    events = kb_activity.recent()
    summary = kb_activity.summarise(events, known_doc_ids=list(meta))
    titles = {k: {"title": v.get("title"), "folder": v.get("folder")} for k, v in meta.items()}
    return jsonify(
        ok=True,
        index=kb_index.status(),
        manifest=kb_store.read_manifest(),
        library={"documents": len(meta),
                 "chunks": sum(int(m.get("chunks") or 0) for m in meta.values()),
                 "embedded": sum(int(m.get("embedded") or 0) for m in meta.values()),
                 "pending": [{"id": m["id"], "title": m.get("title")} for m in meta.values()
                             if m.get("chunks") and not m.get("embedded")][:20],
                 "verified": sum(1 for m in meta.values() if m.get("trust") == "verified")},
        embeddings={"enabled": kb_embed.enabled(), "model": kb_embed.model_name(),
                    "region": kb_embed.location()},
        models={"available": kb_chat.available(),
                "kimi": {"configured": kb_chat.configured("kimi"), "model": kb_chat.KIMI_MODEL,
                         "base": kb_chat.KIMI_BASE},
                "gemini": {"configured": kb_chat.configured("gemini"),
                           "model": kb_chat.GEMINI_MODEL}},
        tracing=kb_trace.status(),
        guide_loaded=bool(kb_prompt.guide_text()),
        retrieval={"rrf_k": kb_index.RRF_K, "candidates": kb_index.CANDIDATES,
                   "limit": kb_index.DEFAULT_LIMIT, "max_per_doc": kb_index.MAX_PER_DOC,
                   "chunk_words": kb_chunk_words(), "semantic_floor": kb_index.SEMANTIC_FLOOR,
                   "trust_nudge": kb_index.TRUST_NUDGE,
                   "superseded_penalty": kb_index.SUPERSEDED_PENALTY},
        activity=summary,
        questions=[e for e in reversed(events) if e.get("kind") in ("question", "search")][:50],
        feedback=kb_feedback.summary(),
        titles=titles,
        storage={"bucket": kb_store.bucket_name(), "prefix": kb_store.PREFIX},
    )


def kb_chunk_words():
    import kb_chunk
    return [kb_chunk.CHUNK_WORDS, kb_chunk.CHUNK_OVERLAP]


@bp.post("/obs/probe")
def obs_probe():
    """Run the REAL retriever and show its working.

    🔴 The same `kb_index.search` the assistant calls, not a copy. A probe that reimplements the
    thing it probes will eventually agree with itself and disagree with production."""
    d = _deny_staff()
    if d:
        return d
    j = _json()
    res = kb_index.search(str(j.get("q") or ""), limit=int(j.get("limit") or 10),
                          folders=j.get("folders") or None,
                          strict=bool(j.get("strict", True)),
                          trust_bonus=bool(j.get("trust_bonus", True)))
    # The same query with trust OFF, so the page can SHOW what the verified nudge and the supersede
    # penalty actually did rather than asserting it.
    plain = kb_index.search(str(j.get("q") or ""), limit=int(j.get("limit") or 10),
                            folders=j.get("folders") or None,
                            strict=bool(j.get("strict", True)), trust_bonus=False)
    return jsonify(ok=True, result=res,
                   without_trust=[{"document_id": e["document_id"], "title": e["title"],
                                   "passage_id": e["passage_id"], "score": e["score"],
                                   "trust": e["trust"]} for e in plain["excerpts"]])


@bp.post("/obs/reach")
def obs_reach():
    """One real call to each configured provider. Costs a few tokens on purpose: a reachability
    check that does not make a request checks nothing."""
    d = _deny_staff()
    if d:
        return d
    import kb_embed
    which = (_json().get("which") or "all").lower()
    out = {}
    if which in ("all", "vertex"):
        out["vertex"] = kb_embed.probe()
    if which in ("all", "kimi") and kb_chat.configured("kimi"):
        out["kimi"] = kb_chat.probe("kimi")
    if which in ("all", "gemini") and kb_chat.configured("gemini"):
        out["gemini"] = kb_chat.probe("gemini")
    return jsonify(ok=True, probes=out)


# --- activity (phase 7 fills this in; the hook exists from the start so every write records) -----

def _log_event(kind, **fields):
    """One line of the usage record. Imported lazily and never allowed to fail a request: a usage
    log that can break an upload is worse than no usage log."""
    try:
        import kb_activity
        kb_activity.log(kind, actor=_actor(), **fields)
    except Exception:                              # noqa: BLE001
        log.debug("kb: activity log skipped", exc_info=True)
