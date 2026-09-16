"""kb_fathom_routes.py - the Meetings page of the knowledge base and the Fathom endpoints behind it.

Registered beside kb_routes with the SAME callables (`init` mirrors kb_routes.init), so who may see
the page, who an action is recorded as, and the local-run production guard are all kb_routes'
decisions - this module adds routes, never rules.

    GET  /kb/meetings                     the page: connection, queue, declared domains, memory
    GET  /kb/api/fathom/status            {connected, webhook, state, unassigned_count, indexed}
    POST /kb/api/fathom/sync              pull meetings since the last sync and run the ladder
    GET  /kb/api/fathom/unassigned        the queue
    POST /kb/api/fathom/assign            {recording_id, client_key | "" | "ignore"}
    GET  /kb/api/fathom/memory/<client>   the client's memory (declared domains, learned, facts)
    POST /kb/api/fathom/memory/<client>   {domains: [..]} | {fact: "..."} | {forget: {kind, key}}
    POST /fathom/webhook                  Fathom -> us; NO session, the HMAC signature is the auth

Secrets: FATHOM_API_KEY + FATHOM_WEBHOOK_SECRET (Secret Manager `fathom-api-key` /
`fathom-webhook-secret`, mounted as env). Unset => the page says "not connected", sync and the
webhook answer 503, and nothing else in the knowledge base changes.
"""
import os
import json
import logging
import threading
import time

from flask import Blueprint, abort, jsonify, redirect, render_template, request

import kb_fathom
import kb_index
import kb_memory
import kb_store

log = logging.getLogger(__name__)

bp = Blueprint("kb_fathom", __name__)

_allowed = _signed_in = _actor = _blocked = _page_ctx = _clients = _entities = _registry_clients = None


def init(app, *, allowed, signed_in, actor, mutation_blocked, page_context, clients, registry_clients,
         entities=None):
    """`clients` is the SESSION-scoped list (the page, Assign) - it reads the Flask session and so may
    only be called inside a request. `registry_clients` is EVERY registry client and reads no session:
    the ladder's closed candidate list, which runs from a webhook (no session at all) and inside a
    background thread (no request context). Confusing the two is how the first level-2 test
    (2026-09-15) produced "classifier unavailable" - the candidate list was empty, not the key.
    `entities` -> {client_key: {names}} from the live dashboards; None = that rung contributes nothing."""
    global _allowed, _signed_in, _actor, _blocked, _page_ctx, _clients, _entities, _registry_clients
    _allowed, _signed_in, _actor, _blocked = allowed, signed_in, actor, mutation_blocked
    _page_ctx, _clients, _entities = page_context, clients, entities or (lambda: {})
    _registry_clients = registry_clients
    app.register_blueprint(bp)


def webhook_secret():
    return os.environ.get("FATHOM_WEBHOOK_SECRET", "")


# --- gates (kb_routes' shape) --------------------------------------------------------------------

def _deny():
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
    d = _deny()
    if d:
        return d
    b = _blocked(what)
    if b:
        return b
    return None


def _known_client(key):
    """A client key the SESSION may file against, or None. "" (agency-wide) is always allowed."""
    ck = kb_store.client_key(key)
    if key in ("", None) or ck == "":
        return "" if key in ("", None) else None
    return ck if ck in {c["key"] for c in _clients()} else None


def _candidates():
    """The CLOSED list the classifier may choose from - every registry client, session-free."""
    return [{"key": c["key"], "name": c.get("name") or c["key"]} for c in _registry_clients()]


# --- the ladder, wired ---------------------------------------------------------------------------

def process(meeting):
    """Run the ladder on one meeting and act on the outcome. -> {"decision", "client_key", ...}.
    A classifier hiccup queues the meeting; it never raises past here for that."""
    already = kb_fathom.already_indexed(meeting)
    if already is not None:
        return {"decision": "exists", "client_key": already}
    memories = kb_memory.load_all()
    try:
        res = kb_fathom.classify(meeting, kb_memory.all_client_domains(memories), memories, _candidates(),
                                 entities_by_client=_safe_entities())
    except Exception:                        # noqa: BLE001
        log.exception("fathom: classify failed - queuing")
        res = {"decision": "queue", "client_key": None, "assigned_by": None, "confidence": 0.0,
               "evidence": ["classifier error"], "proposal": None}
    rid = kb_fathom.recording_id(meeting)
    log.info("fathom %s: %s %r by=%s conf=%.2f evidence=%s", rid, res["decision"], res.get("client_key"),
             res.get("assigned_by"), res.get("confidence") or 0, "; ".join(res.get("evidence") or [])[:400])
    if res["decision"] == "assign":
        kb_fathom.index_meeting(meeting, res["client_key"], res["assigned_by"], evidence=res.get("evidence"))
    else:
        kb_fathom.store_unassigned(meeting, proposal=res.get("proposal") or {"evidence": res.get("evidence")})
    return res


def accept(meeting):
    """The FAST half of a webhook: park the meeting in the queue (no proposal yet) so it is visible
    and safe, then hand the slow ladder to a background thread. Returns before any dashboard is
    fetched or any model is called.

    🔴 WHY: Fathom (Svix-style) expects an answer within seconds and retries otherwise. The evidence
    rung reads every live dashboard's data.json - measured at over two minutes on 2026-09-15 for 18
    dashboards on a cold cache - so running the ladder before replying made every real delivery a
    timeout. The queue write happens BEFORE the reply, so even if the background work is starved
    (Cloud Run throttles CPU after a response unless the service has CPU always allocated), the
    meeting is never lost: it waits for a person with no proposal, which is the pilot's honest
    fallback. `already_indexed` is one GET and stays synchronous so a re-delivery is a no-op.
    -> {"decision": "accepted"|"exists", "client_key"}."""
    already = kb_fathom.already_indexed(meeting)
    if already is not None:
        return {"decision": "exists", "client_key": already}
    kb_fathom.store_unassigned(meeting, proposal=None)
    t = threading.Thread(target=_process_quietly, args=(meeting,), name="fathom-ladder", daemon=True)
    t.start()
    return {"decision": "accepted", "client_key": None}


def _process_quietly(meeting):
    try:
        process(meeting)
    except Exception:                        # noqa: BLE001 - the meeting is already in the queue
        log.exception("fathom: background ladder failed for %s", kb_fathom.recording_id(meeting))


def _safe_entities():
    try:
        return _entities() or {}
    except Exception:                        # noqa: BLE001
        log.exception("fathom: entity harvest failed")
        return {}


def _indexed_count():
    try:
        # all_meta -> {doc_id: meta}. Iterating it directly yields KEYS (strings): the counter read
        # 0 on the first real sync (2026-09-16) while two meetings were filed. Same slip was in
        # kb_bridge and corpus_vote, and the tests had mocked all_meta as a LIST, which is why it passed.
        return sum(1 for m in kb_index.all_meta(include_archived=False).values()
                   if m.get("kind") == kb_fathom.KIND and m.get("source") == kb_fathom.SOURCE)
    except Exception:                        # noqa: BLE001
        return 0


# --- page ----------------------------------------------------------------------------------------

@bp.get("/kb/meetings")
def meetings_page():
    d = _deny_page()
    if d:
        return d
    return render_template("kb_meetings.html", actor=_actor(), page="meetings",
                           clients=_clients(), connected=kb_fathom.enabled(),
                           webhook=bool(webhook_secret()), **_page_ctx())


# --- api -----------------------------------------------------------------------------------------

@bp.get("/kb/api/fathom/status")
def status():
    d = _deny()
    if d:
        return d
    st, queue = {}, []
    try:
        st = kb_fathom.state()
        queue = kb_fathom.list_unassigned()
    except Exception:                        # noqa: BLE001
        log.exception("fathom status")
    return jsonify(ok=True, connected=kb_fathom.enabled(), webhook=bool(webhook_secret()), state=st,
                   unassigned=queue, indexed=_indexed_count(), auto_assign=kb_fathom.AUTO_ASSIGN,
                   auto_file=sorted(kb_fathom.AUTO_FILE), queue_titles=kb_fathom.QUEUE_TITLES)


@bp.post("/kb/api/fathom/sync")
def sync():
    """Pull meetings since the last sync (first run: `since` in the body, default 30 days)."""
    g = _guard_write("fathom sync")
    if g:
        return g
    if not kb_fathom.enabled():
        return jsonify(ok=False, error="Fathom is not connected (FATHOM_API_KEY unset)."), 503
    d = request.get_json(silent=True) or {}
    st = kb_fathom.state()
    if st.get("sync_in_progress") and time.time() - float(st.get("sync_started_ts") or 0) < 1800:
        return jsonify(ok=False, error="A sync is already running.", state=st), 409
    since = (d.get("since") or st.get("last_created_after") or
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 30 * 86400)))
    st.update(sync_in_progress=True, sync_started_ts=time.time(), by=_actor())
    kb_fathom.save_state(st)
    # The same rule as the webhook: reply now, work in the background. A 30-meeting first sync on a
    # cold entity cache is minutes, and a button that hangs for minutes reads as broken.
    threading.Thread(target=_sync_quietly, args=(os.environ["FATHOM_API_KEY"], since, _actor()),
                     name="fathom-sync", daemon=True).start()
    return jsonify(ok=True, started=True, since=since, state=st)


def _needs_retry(item):
    """A queued meeting whose ladder never produced a proposal (a classifier error, an old bug): the
    card shows no guess, and nothing would ever revisit it. Sync gives it another run."""
    p = item.get("proposal") or {}
    return "client_key" not in p


def retry_unproposed(counts):
    """Re-run the ladder over queued meetings with no proposal. Found necessary on the first real sync
    (2026-09-16): seven meetings were queued by a crash in the evidence rung and the next sync,
    which only pulls meetings NEWER than the watermark, would never have touched them again."""
    for item in kb_fathom.list_unassigned():
        if not _needs_retry(item):
            continue
        meeting = kb_fathom.load_unassigned(item["recording_id"])
        if meeting is None:
            continue
        counts["retried"] = counts.get("retried", 0) + 1
        try:
            res = process(meeting)
            counts["assigned" if res["decision"] == "assign" else "exists" if res["decision"] == "exists" else "queued"] += 1
        except Exception:                    # noqa: BLE001
            counts["errors"] += 1
            log.exception("fathom sync: retry failed for %s", item["recording_id"])


def _sync_quietly(api_key, since, actor):
    counts = {"seen": 0, "assigned": 0, "queued": 0, "exists": 0, "errors": 0}
    newest, error = since, ""
    try:
        for m in kb_fathom.fetch_meetings(api_key, created_after=since):
            counts["seen"] += 1
            try:
                res = process(m)
                counts["assigned" if res["decision"] == "assign" else "exists" if res["decision"] == "exists" else "queued"] += 1
            except Exception:                # noqa: BLE001
                counts["errors"] += 1
                log.exception("fathom sync: meeting failed")
            newest = max(newest, str(m.get("created_at") or ""))
        retry_unproposed(counts)
    except Exception as e:                   # noqa: BLE001
        log.exception("fathom sync failed")
        error = f"Sync failed: {str(e)[:160]}"
    st = kb_fathom.state()
    st.update(sync_in_progress=False, last_sync_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              last_counts=counts, by=actor, last_error=error)
    if not error:
        st["last_created_after"] = newest
    kb_fathom.save_state(st)


@bp.get("/kb/api/fathom/unassigned")
def unassigned():
    d = _deny()
    if d:
        return d
    try:
        return jsonify(ok=True, items=kb_fathom.list_unassigned())
    except Exception:                        # noqa: BLE001
        log.exception("unassigned list failed")
        return jsonify(ok=False, error="Could not list the queue."), 500


@bp.post("/kb/api/fathom/assign")
def assign():
    """Body: {recording_id, client_key, skip?}. client_key = a registry key, "" (agency-wide) or
    "ignore". `skip` = the will_learn items the person unticked (emails, domains, the title)."""
    d = request.get_json(silent=True) or {}
    rid = str(d.get("recording_id") or "").strip()
    raw = d.get("client_key")
    skip = [str(s) for s in (d.get("skip") or []) if isinstance(s, (str, int))][:50]
    g = _guard_write(f"fathom assign {rid}")
    if g:
        return g
    if not rid or raw is None:
        return jsonify(ok=False, error="recording_id and client_key are required."), 400
    if raw != "ignore":
        ck = _known_client(raw)
        if ck is None:
            return jsonify(ok=False, error="Unknown client."), 404
    meeting = kb_fathom.load_unassigned(rid)
    if meeting is None:
        return jsonify(ok=False, error="No such meeting in the queue."), 404
    if raw == "ignore":
        kb_fathom.drop_unassigned(rid)
        log.info("fathom %s ignored by %s", rid, _actor())
        return jsonify(ok=True, ignored=True)
    try:
        meta = kb_fathom.index_meeting(meeting, ck, "human", evidence=[f"assigned by {_actor()}"], actor=_actor(),
                                       skip_learning=skip)
    except Exception:                        # noqa: BLE001
        log.exception("fathom assign failed")
        return jsonify(ok=False, error="Could not file the meeting - please try again."), 502
    return jsonify(ok=True, doc=meta)


@bp.post("/kb/api/fathom/rebuild")
def rebuild():
    """Body: {recording_id}. Re-derives a filed meeting's text from its raw file (maintenance)."""
    d = request.get_json(silent=True) or {}
    rid = str(d.get("recording_id") or "").strip()
    g = _guard_write(f"fathom rebuild {rid}")
    if g:
        return g
    if not rid:
        return jsonify(ok=False, error="recording_id is required."), 400
    try:
        meta = kb_fathom.rebuild_document(rid)
    except Exception:                        # noqa: BLE001
        log.exception("fathom rebuild failed")
        return jsonify(ok=False, error="Could not rebuild."), 502
    if meta is None:
        return jsonify(ok=False, error="No filed meeting with that id."), 404
    return jsonify(ok=True, doc=meta)


@bp.get("/kb/api/fathom/memory/<client>")
def memory_get(client):
    d = _deny()
    if d:
        return d
    ck = _known_client(client)
    if ck is None:
        return jsonify(ok=False, error="Unknown client."), 404
    try:
        return jsonify(ok=True, client=ck, memory=kb_memory.load(ck))
    except Exception:                        # noqa: BLE001
        log.exception("memory load failed")
        return jsonify(ok=False, error="Could not load."), 500


@bp.post("/kb/api/fathom/memory/<client>")
def memory_edit(client):
    """One of: {domains: [..]} sets the declared domains; {fact: ".."} adds a fact;
    {forget: {kind, key}} removes one entry."""
    g = _guard_write(f"fathom memory {client}")
    if g:
        return g
    ck = _known_client(client)
    if ck is None:
        return jsonify(ok=False, error="Unknown client."), 404
    d = request.get_json(silent=True) or {}
    if "domains" in d:
        saved, bad = kb_memory.set_client_domains(ck, d.get("domains") or [])
        if bad:
            return jsonify(ok=False, error=f"Not a domain: {', '.join(bad[:3])}"), 400
        return jsonify(ok=True, memory=kb_memory.load(ck))
    if "fact" in d:
        if not (d.get("fact") or "").strip():
            return jsonify(ok=False, error="Empty fact."), 400
        return jsonify(ok=True, memory=kb_memory.add_fact(ck, d["fact"]))
    if "forget" in d:
        f = d.get("forget") or {}
        kind, key = (f.get("kind") or "").strip(), str(f.get("key") or "").strip()
        if kind not in kb_memory.ALL_KINDS or not key:
            return jsonify(ok=False, error="kind and key are required."), 400
        return jsonify(ok=True, removed=kb_memory.forget(ck, kind, key), memory=kb_memory.load(ck))
    return jsonify(ok=False, error="Nothing to do."), 400


# --- webhook (no session) ------------------------------------------------------------------------

@bp.post("/fathom/webhook")
def webhook():
    """Fathom -> us. The HMAC signature IS the auth, verified on the RAW body."""
    secret = webhook_secret()
    if not secret:
        return jsonify(ok=False, error="not configured"), 503
    raw = request.get_data()
    if not kb_fathom.verify_signature(dict(request.headers), raw, secret):
        log.warning("fathom webhook: bad signature from %s", request.remote_addr)
        return jsonify(ok=False, error="bad signature"), 401
    try:
        meeting = json.loads(raw)
    except Exception:                        # noqa: BLE001
        return jsonify(ok=False, error="bad json"), 400
    if not isinstance(meeting, dict) or not kb_fathom.recording_id(meeting):
        return jsonify(ok=False, error="no recording_id"), 400
    b = _blocked("fathom webhook ingest")
    if b:
        return b
    try:
        res = accept(meeting)                # queue first, reply now, ladder in the background
    except Exception:                        # noqa: BLE001
        log.exception("fathom webhook: could not queue")
        return jsonify(ok=False, error="ingest failed"), 500
    return jsonify(ok=True, decision=res["decision"], client_key=res.get("client_key"))
