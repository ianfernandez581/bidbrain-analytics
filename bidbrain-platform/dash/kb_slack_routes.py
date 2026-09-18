"""kb_slack_routes.py - the Channels page and its API, plus Slack's inbound endpoint.

    GET  /kb/channels                    the page (same gate as /kb/meetings)
    GET  /kb/api/slack/status            connection, channels the bot is in (+ their client mapping), queue
    POST /kb/api/slack/map               {channel_id, client_key|null, name?}   a PERSON declares the client
    POST /kb/api/slack/refile            {channel_id}   second, explicit step: re-file that channel's docs
    POST /kb/api/slack/sync              {since_days?}  pull every member channel; reply now, work in the background
    GET  /kb/api/slack/unassigned        the queue
    POST /kb/api/slack/assign            {key, client_key|"ignore", skip?}   skip = will_learn items unticked
    GET  /kb/api/slack/log?kind=         the audit record, Slack kinds only (server-side filter)
    POST /slack/events                   Slack -> us: url_verification, message events, uninstall

The filing rule is kb_slack's: a mapped channel files with assigned_by="channel"; an unmapped one
goes through kb_fathom.classify exactly as a meeting would. See kb_slack.py's header.
"""
import hmac
import json
import logging
import os
import threading
import time

from flask import Blueprint, abort, jsonify, redirect, render_template, request

import kb_fathom
import kb_index
import kb_memory
import kb_slack
import kb_store

log = logging.getLogger("kb_slack_routes")
bp = Blueprint("kb_slack", __name__)

_allowed = _signed_in = _actor = _blocked = _page_ctx = _clients = _entities = _registry_clients = None


def init(app, *, allowed, signed_in, actor, mutation_blocked, page_context, clients, registry_clients,
         entities=None):
    """Same contract as kb_fathom_routes.init - `clients` is session-scoped (the page), `registry_clients`
    reads no session (the ladder, from a webhook or a background thread)."""
    global _allowed, _signed_in, _actor, _blocked, _page_ctx, _clients, _entities, _registry_clients
    _allowed, _signed_in, _actor, _blocked = allowed, signed_in, actor, mutation_blocked
    _page_ctx, _clients, _entities = page_context, clients, entities or (lambda: {})
    _registry_clients = registry_clients
    app.register_blueprint(bp)


# --- gates (kb_fathom_routes' shape) -------------------------------------------------------------

def _deny():
    if not _signed_in():
        return jsonify(ok=False, error="Sign in first.", reason="auth"), 401
    if not _allowed():
        return jsonify(ok=False, error="The knowledge base is internal."), 403
    return None


def _deny_page():
    if not _signed_in():
        return redirect("/")
    if not _allowed():
        abort(403)
    return None


def cron_secret():
    """Shared secret for the scheduled catch-up sync. Unset = the endpoint is off (503)."""
    return os.environ.get("SLACK_CRON_SECRET", "")


def _guard_write(what):
    d = _deny()
    if d:
        return d
    return _blocked(what)


def _known_client(key):
    """"" (agency-wide) or a registry key -> the key; anything else -> None."""
    if key == "" or key is None:
        return ""
    ck = kb_store.client_key(str(key))
    if not ck:
        return None
    return ck if any(c.get("key") == ck for c in _registry_clients()) else None


def _candidates():
    return [{"key": c["key"], "name": c.get("name") or c["key"], "desc": c.get("desc", "")}
            for c in _registry_clients() if c.get("key")]


def _safe_entities():
    try:
        return _entities() or {}
    except Exception:                        # noqa: BLE001
        log.exception("slack: entity harvest failed")
        return {}


def _audit(kind, conv_or_key, *, actor="", **fields):
    """One line in the activity record for a Slack DECISION. Never breaks the pipeline (the
    kb_fathom_routes._audit rule); `title` may be supplied by the caller and is popped so
    log_event is never handed the keyword twice."""
    try:
        import kb_activity
        if isinstance(conv_or_key, dict):
            key = kb_slack.doc_id(conv_or_key["channel"]["id"], conv_or_key["key"])
            title = kb_slack.conversation_title(conv_or_key, _users_cached())
            channel = conv_or_key["channel"].get("name", "")
        else:
            key, title, channel = str(conv_or_key or ""), "", ""
        title = str(fields.pop("title", "") or title)[:200]
        channel = str(fields.pop("channel", "") or channel)[:80]
        kb_activity.log_event(kind, actor=actor or _actor(), recording_id=key, title=title, channel=channel, **fields)
    except Exception:                        # noqa: BLE001
        log.debug("slack: activity record for %s was NOT written", kind, exc_info=True)


def _users_cached():
    """The directory if it is already cached; never a network call from an audit line."""
    return kb_slack._USERS.get("by_id") or {}       # noqa: SLF001 - same module family


def _users_for_writing():
    """The directory for a call that WRITES a document. Unlike _users_cached this may fetch: a cold
    cache would otherwise bake raw `U…` ids into a permanent document, and nothing re-renders it.
    Falls back to the cache if Slack is unreachable - a filing must not fail over the directory."""
    try:
        return kb_slack.users()
    except Exception:                        # noqa: BLE001
        log.warning("slack: directory unavailable at filing time - names may render as ids")
        return _users_cached()


# --- the ladder, per conversation ----------------------------------------------------------------

def process(conv, ctx):
    """Decide where one conversation goes and act. `ctx` = {"users", "channels", "team_url", "cm"}.
    -> {"decision": "exists"|"rebuilt"|"assign"|"queue", "client_key", ...}."""
    did = kb_slack.doc_id(conv["channel"]["id"], conv["key"])
    already = kb_slack.already_indexed(did)
    if already is not None:
        # Filed before: REBUILD from history under the same client (this is how an edit or a delete
        # upstream reaches the library). reindex_document is idempotent, so an unchanged body is free.
        doc = kb_store.read_doc(did) or {}
        by = (doc.get("slack") or {}).get("assigned_by") or "channel"
        kb_slack.index_conversation(conv, already, by, evidence=(doc.get("slack") or {}).get("assignment_evidence"),
                                    users_by_id=ctx["users"], channels_by_id=ctx["channels"], team_url=ctx["team_url"])
        return {"decision": "rebuilt", "client_key": already}
    mapped = kb_slack.channel_client(conv["channel"]["id"], ctx["cm"])
    if mapped is not None:
        ev = [f"channel #{conv['channel']['name']} is mapped to {mapped or 'agency-wide'} by a person"]
        meta = kb_slack.index_conversation(conv, mapped, "channel", evidence=ev, users_by_id=ctx["users"],
                                           channels_by_id=ctx["channels"], team_url=ctx["team_url"])
        _audit("slack_filed", conv, actor="slack", client=mapped, by="channel", confidence=1.0,
               evidence="; ".join(ev), doc_id=meta.get("id", ""))
        return {"decision": "assign", "client_key": mapped, "assigned_by": "channel"}
    # Nobody has said: the same ladder a meeting gets, over a meeting-shaped view.
    m = kb_slack.as_meeting(conv, ctx["users"])
    memories = kb_memory.load_all()
    try:
        res = kb_fathom.classify(m, kb_memory.all_client_domains(memories), memories, _candidates(),
                                 entities_by_client=_safe_entities())
    except Exception:                        # noqa: BLE001
        log.exception("slack: classify failed - queuing")
        res = {"decision": "queue", "client_key": None, "assigned_by": None, "confidence": 0.0,
               "evidence": ["classifier error"], "proposal": None}
    prop = res.get("proposal") or {}
    if res["decision"] == "assign":
        meta = kb_slack.index_conversation(conv, res["client_key"], res["assigned_by"], evidence=res.get("evidence"),
                                           users_by_id=ctx["users"], channels_by_id=ctx["channels"], team_url=ctx["team_url"])
        _audit("slack_filed", conv, actor="slack", client=res["client_key"], by=res.get("assigned_by"),
               confidence=round(float(res.get("confidence") or 0), 3), why=(prop.get("why") or "")[:400],
               evidence="; ".join(res.get("evidence") or [])[:600], doc_id=meta.get("id", ""))
        return res
    queued_before = kb_slack.load_unassigned(did) is not None
    kb_slack.store_unassigned(conv, proposal=prop or {"evidence": res.get("evidence")}, users_by_id=ctx["users"])
    if not queued_before:                    # a day-doc grows all day; log the wait once
        _audit("slack_queued", conv, actor="slack", guess=prop.get("client_key", ""),
               by=prop.get("sure_by") or "model", confidence=round(float(res.get("confidence") or 0), 3),
               why=(prop.get("why") or "")[:400], evidence="; ".join(res.get("evidence") or [])[:600])
    return res


def _context(tok):
    st = kb_slack.state()
    team = st.get("team") or {}
    if not team.get("url"):
        try:
            team = kb_slack.auth_test(tok=tok)
            st["team"] = team
            kb_slack.save_state(st)
        except Exception:                    # noqa: BLE001 - the permalink degrades, filing does not
            log.exception("slack: auth.test failed")
    users = kb_slack.users(tok=tok)
    chans = {c["id"]: c for c in kb_slack.list_channels(tok=tok)}
    return {"users": users, "channels": chans, "team_url": team.get("url", ""), "cm": kb_slack.channel_map(),
            "member_channels": list(chans.values())}


def sync_channel(ch, ctx, since_ts, counts, tok=None):
    """One channel: read history since (its watermark - lookback), group, decide each conversation."""
    st = kb_slack.state()
    rec = (st.get("channels") or {}).get(ch["id"]) or {}
    last = float(rec.get("last_ts") or 0)
    oldest = max(since_ts, last - kb_slack.LOOKBACK_S) if last else since_ts
    msgs, limited = kb_slack.fetch_history(ch["id"], oldest=f"{oldest:.6f}", tok=tok)
    newest = max([float(m.get("ts") or 0) for m in msgs] + [last])
    for conv in kb_slack.group_conversations(msgs, ch):
        counts["seen"] += 1
        try:
            res = process(conv, ctx)
            counts[{"assign": "filed", "queue": "queued", "rebuilt": "rebuilt", "exists": "rebuilt"}.get(res["decision"], "queued")] += 1
        except Exception:                    # noqa: BLE001
            counts["errors"] += 1
            log.exception("slack sync: conversation failed in #%s", ch.get("name"))
    st = kb_slack.state()                    # re-read: process() may have written the team block
    st.setdefault("channels", {})[ch["id"]] = {"name": ch["name"], "is_private": ch.get("is_private", False),
                                               "last_ts": f"{newest:.6f}", "is_limited": limited,
                                               "synced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                               "messages_seen": len(msgs)}
    kb_slack.save_state(st)


def _sync_quietly(tok, since_ts, actor, only_channel=None):
    counts = {"seen": 0, "filed": 0, "queued": 0, "rebuilt": 0, "errors": 0, "channels": 0}
    error = ""
    try:
        ctx = _context(tok)
        for ch in ctx["member_channels"]:
            if only_channel and ch["id"] != only_channel:
                continue
            if not kb_slack.readable(ch):
                counts["skipped_private"] = counts.get("skipped_private", 0) + 1
                log.info("slack sync: #%s is private and SLACK_ALLOW_PRIVATE is off - skipped", ch.get("name"))
                continue
            counts["channels"] += 1
            try:
                sync_channel(ch, ctx, since_ts, counts, tok=tok)
            except Exception as e:           # noqa: BLE001
                counts["errors"] += 1
                error = f"#{ch.get('name')}: {str(e)[:120]}"
                log.exception("slack sync: channel #%s failed", ch.get("name"))
    except Exception as e:                   # noqa: BLE001
        log.exception("slack sync failed")
        error = f"Sync failed: {str(e)[:160]}"
    st = kb_slack.state()
    st.update(sync_in_progress=False, last_sync_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              last_counts=counts, by=actor, last_error=error)
    kb_slack.save_state(st)


# --- page + api ----------------------------------------------------------------------------------

@bp.get("/kb/slack-notice")
def slack_notice():
    """The PUBLIC privacy notice. No login, deliberately - Slack's Developer Policy requires a
    "publicly available and easily accessible" policy for an app that stores workspace data, and
    the announcement in Slack points at this page.

    🔴 KEEP IT STATIC. It is the only ungated route on this service, so it must render fixed text
    and read nothing: no session, no registry, no query parameter, no knowledge-base content. If
    this page ever needs a live value, gate it or put the value somewhere else.
    """
    return render_template("kb_slack_notice.html")


@bp.get("/kb/channels")
def channels_page():
    d = _deny_page()
    if d:
        return d
    return render_template("kb_channels.html", actor=_actor(), page="channels", clients=_clients(),
                           connected=kb_slack.enabled(), events=bool(kb_slack.signing_secret()), **_page_ctx())


def _indexed_count():
    try:
        return sum(1 for m in kb_index.all_meta(include_archived=False).values() if m.get("source") == kb_slack.SOURCE)
    except Exception:                        # noqa: BLE001
        return 0


@bp.get("/kb/api/slack/status")
def status():
    d = _deny()
    if d:
        return d
    st, queue, chans, team, err = {}, [], [], {}, ""
    try:
        st = dict(kb_slack.state())
        st["sync_in_progress"] = kb_slack.syncing(st)
        team = st.get("team") or {}
        queue = kb_slack.list_unassigned()
    except Exception:                        # noqa: BLE001
        log.exception("slack status")
    cm = kb_slack.channel_map()
    if kb_slack.enabled() and request.args.get("live", "1") != "0":
        try:
            for c in kb_slack.list_channels():
                rec = (st.get("channels") or {}).get(c["id"]) or {}
                m = cm.get(c["id"])
                chans.append(dict(c, readable=kb_slack.readable(c), mapped=m is not None, client=(m or {}).get("client"),
                                  mapped_by=(m or {}).get("by", ""), last_synced=rec.get("synced_at", ""),
                                  is_limited=bool(rec.get("is_limited")), messages_seen=rec.get("messages_seen", 0)))
        except Exception as e:               # noqa: BLE001
            err = f"Slack did not answer: {str(e)[:160]}"
            log.exception("slack status: channels")
    return jsonify(ok=True, connected=kb_slack.enabled(), events=bool(kb_slack.signing_secret()), team=team,
                   state=st, channels=chans, channels_error=err, unassigned=queue, indexed=_indexed_count(),
                   auto_assign=kb_fathom.AUTO_ASSIGN, allow_private=kb_slack.ALLOW_PRIVATE)


@bp.post("/kb/api/slack/map")
def map_channel():
    """A person declares which client a channel belongs to ('' = agency-wide; null clears it). This
    changes how FUTURE conversations file; already-filed ones move only via /refile, a second click."""
    d = request.get_json(silent=True) or {}
    cid = str(d.get("channel_id") or "").strip()
    g = _guard_write(f"slack map {cid}")
    if g:
        return g
    if not cid:
        return jsonify(ok=False, error="channel_id is required."), 400
    raw = d.get("client_key", None)
    before = kb_slack.channel_client(cid)
    if raw is None:
        cm = kb_slack.set_channel_client(cid, None)
        _audit("slack_mapped", cid, client=None, guess=before, by="human", channel=d.get("name", ""),
               title=f"#{d.get('name', cid)}", note="mapping cleared")
        return jsonify(ok=True, channels=cm)
    ck = _known_client(raw)
    if ck is None:
        return jsonify(ok=False, error="Unknown client."), 404
    cm = kb_slack.set_channel_client(cid, ck, name=d.get("name", ""), by=_actor())
    _audit("slack_mapped", cid, client=ck, guess=before, by="human", channel=d.get("name", ""),
           title=f"#{d.get('name', cid)}")
    return jsonify(ok=True, channels=cm, client=ck)


@bp.post("/kb/api/slack/refile")
def refile():
    """Move every already-filed conversation of a channel to its CURRENT mapping. Explicit and
    separate from /map on purpose (the K7-10 safe-Assign rule): nothing re-files on a dropdown change."""
    d = request.get_json(silent=True) or {}
    cid = str(d.get("channel_id") or "").strip()
    g = _guard_write(f"slack refile {cid}")
    if g:
        return g
    target = kb_slack.channel_client(cid)
    if target is None:
        return jsonify(ok=False, error="Map the channel to a client first."), 400
    moved = 0
    for did, m in kb_index.all_meta(include_archived=False).items():
        if m.get("source") != kb_slack.SOURCE or not str(did).startswith(f"slack-{cid}-"):
            continue
        doc = kb_store.read_doc(did)
        if not doc or (doc.get("client") or "") == target:
            continue
        was = doc.get("client") or ""
        doc["client"] = target
        doc.setdefault("slack", {})["assigned_by"] = "channel"
        kb_index.reindex_document(doc, force=True)
        _audit("slack_moved", did, client=target, guess=was, by="human", title=doc.get("title", ""),
               channel=(doc.get("slack") or {}).get("channel_name", ""))
        moved += 1
    return jsonify(ok=True, moved=moved, client=target)


@bp.post("/kb/api/slack/sync")
def sync():
    g = _guard_write("slack sync")
    if g:
        return g
    if not kb_slack.enabled():
        return jsonify(ok=False, error="Slack is not connected (SLACK_BOT_TOKEN unset)."), 503
    d = request.get_json(silent=True) or {}
    st = kb_slack.state()
    if kb_slack.syncing(st):
        return jsonify(ok=False, error="A sync is already running.", state=st), 409
    try:
        days = max(1, min(3650, int(d.get("since_days") or 30)))
    except (TypeError, ValueError):
        days = 30
    since_ts = time.time() - days * 86400
    st.update(sync_in_progress=True, sync_started_ts=time.time(), by=_actor())
    kb_slack.save_state(st)
    threading.Thread(target=_sync_quietly, args=(kb_slack.token(), since_ts, _actor()),
                     name="slack-sync", daemon=True).start()
    return jsonify(ok=True, started=True, since_days=days, state=st)


@bp.post("/slack/cron/sync")
def cron_sync():
    """Scheduler -> us. A catch-up sweep for anything the events path missed (service down, Slack
    gave up retrying, a reply to an old thread). No session: the shared secret IS the auth, the
    same shape as the Fathom webhook. Safe to run on a timer - a document that has not changed is
    rebuilt to the identical bytes and reindex_document reports it skipped.

    Header:  X-Bidbrain-Cron: <SLACK_CRON_SECRET>
    Body:    {"since_days": N}  (optional, default SLACK_CRON_DAYS or 7, clamped 1..3650)
    """
    secret = cron_secret()
    if not secret:
        return jsonify(ok=False, error="not configured"), 503
    given = request.headers.get("X-Bidbrain-Cron", "")
    if not hmac.compare_digest(given, secret):
        log.warning("slack cron sync: bad secret from %s", request.remote_addr)
        return jsonify(ok=False, error="bad secret"), 401
    if not kb_slack.enabled():
        return jsonify(ok=False, error="Slack is not connected (SLACK_BOT_TOKEN unset)."), 503
    b = _blocked("slack cron sync")
    if b:
        return b
    st = kb_slack.state()
    if kb_slack.syncing(st):
        # Not an error: the nightly run simply steps aside for whatever is already running.
        return jsonify(ok=True, started=False, reason="a sync is already running"), 200
    d = request.get_json(silent=True) or {}
    try:
        days = max(1, min(3650, int(d.get("since_days") or os.environ.get("SLACK_CRON_DAYS") or 7)))
    except (TypeError, ValueError):
        days = 7
    since_ts = time.time() - days * 86400
    st.update(sync_in_progress=True, sync_started_ts=time.time(), by="scheduler")
    kb_slack.save_state(st)
    threading.Thread(target=_sync_quietly, args=(kb_slack.token(), since_ts, "scheduler"),
                     name="slack-cron-sync", daemon=True).start()
    return jsonify(ok=True, started=True, since_days=days), 202


@bp.get("/kb/api/slack/unassigned")
def unassigned():
    d = _deny()
    if d:
        return d
    return jsonify(ok=True, items=kb_slack.list_unassigned())


@bp.post("/kb/api/slack/assign")
def assign():
    """Body: {key, client_key}. client_key = a registry key, "" (agency-wide) or "ignore"."""
    d = request.get_json(silent=True) or {}
    key = str(d.get("key") or "").strip()
    raw = d.get("client_key")
    skip = [str(s) for s in (d.get("skip") or []) if isinstance(s, (str, int))][:50]
    g = _guard_write(f"slack assign {key}")
    if g:
        return g
    if not key or raw is None:
        return jsonify(ok=False, error="key and client_key are required."), 400
    if raw != "ignore":
        ck = _known_client(raw)
        if ck is None:
            return jsonify(ok=False, error="Unknown client."), 404
    rec = kb_slack.load_unassigned(key)
    if rec is None:
        return jsonify(ok=False, error="No such conversation in the queue."), 404
    conv, prop = rec.get("conversation") or {}, rec.get("proposal") or {}
    if raw == "ignore":
        _audit("slack_ignored", conv, guess=prop.get("client_key", ""),
               confidence=round(float(prop.get("confidence") or 0), 3), why=(prop.get("why") or "")[:400])
        kb_slack.drop_unassigned(key)
        return jsonify(ok=True, ignored=True)
    st = kb_slack.state()
    try:
        meta = kb_slack.index_conversation(conv, ck, "human", evidence=[f"assigned by {_actor()}"], actor=_actor(),
                                           users_by_id=_users_for_writing(), team_url=(st.get("team") or {}).get("url", ""),
                                           skip_learning=skip)
    except Exception:                        # noqa: BLE001
        log.exception("slack assign failed")
        return jsonify(ok=False, error="Could not file the conversation - please try again."), 502
    _audit("slack_assigned", conv, client=ck, by="human", guess=prop.get("client_key", ""),
           agreed=(prop.get("client_key", "") == ck) if prop else None,
           confidence=round(float(prop.get("confidence") or 0), 3), skipped="; ".join(skip)[:300],
           doc_id=meta.get("id", ""))
    return jsonify(ok=True, doc=meta)


@bp.get("/kb/api/slack/purge-check")
def purge_check():
    """How many Slack-derived objects still exist, and when the last purge ran. The Developer Policy
    gives 14 business days after uninstall; this is the number a scheduler (or a person) asserts is
    zero. Read-only."""
    d = _deny()
    if d:
        return d
    docs = sum(1 for did, m in kb_index.all_meta(include_archived=True).items()
               if m.get("source") == kb_slack.SOURCE or str(did).startswith("slack-"))
    objects = 0
    try:
        objects = sum(1 for _ in kb_store._storage().list_blobs(kb_store.bucket_name(),             # noqa: SLF001
                                                                 prefix=f"{kb_store.PREFIX}/slack/"))
    except Exception:                        # noqa: BLE001
        log.exception("slack purge-check: objects")
    import kb_activity
    purges = [e for e in kb_activity.recent() if e.get("kind") == "slack_purged"]
    last = max((e.get("at") or 0) for e in purges) if purges else 0
    return jsonify(ok=True, documents=docs, objects=objects, last_purge_at=last,
                   clean=(docs == 0 and objects == 0), connected=kb_slack.enabled())


@bp.get("/kb/api/slack/log")
def slack_log():
    """The audit record, Slack kinds only. The filter is HERE, not on the page (the Meetings rule)."""
    d = _deny()
    if d:
        return d
    import kb_activity
    want = (request.args.get("kind") or "").strip()
    try:
        limit = max(1, min(500, int(request.args.get("limit") or 200)))
    except ValueError:
        limit = 200
    try:
        events = kb_activity.recent()
    except Exception:                        # noqa: BLE001
        log.exception("slack: could not read the activity record")
        return jsonify(ok=False, error="The record could not be read.", events=[], counts={}), 200
    mine = [e for e in events if kb_activity.kind_group(e.get("kind")) == "slack"]
    counts = {}
    for e in mine:
        counts[e.get("kind")] = counts.get(e.get("kind"), 0) + 1
    if want:
        mine = [e for e in mine if e.get("kind") == want]
    return jsonify(ok=True, events=list(reversed(mine))[:limit], counts=counts,
                   kinds=list(kb_activity.GROUPS["slack"]), total=len(mine))


# --- Slack -> us -----------------------------------------------------------------------------------

_SEEN_EVENTS = {}                            # event_id -> ts, a per-process fast path before the inbox


def _inbox_seen(event_id):
    if not event_id:
        return False
    if event_id in _SEEN_EVENTS:
        return True
    return kb_store._read_json(f"{kb_slack._INBOX}/{event_id}.json", default=None) is not None   # noqa: SLF001


def _inbox_keep(event_id, payload):
    _SEEN_EVENTS[event_id] = time.time()
    if len(_SEEN_EVENTS) > 5000:
        for k in sorted(_SEEN_EVENTS, key=_SEEN_EVENTS.get)[:2500]:
            _SEEN_EVENTS.pop(k, None)
    try:
        kb_store._write_json(f"{kb_slack._INBOX}/{event_id}.json", payload)                     # noqa: SLF001
    except Exception:                        # noqa: BLE001
        log.exception("slack: inbox write failed for %s", event_id)


def _purge_quietly(reason):
    try:
        counts = kb_slack.purge_all()
        log.warning("slack: purged everything (%s): %s", reason, counts)
        _audit("slack_purged", "", actor="slack", note=reason, docs=counts.get("docs", 0), objects=counts.get("objects", 0),
               title="app removed from Slack")
    except Exception:                        # noqa: BLE001
        log.exception("slack: purge failed")


def _channel_change_quietly(kind, ev):
    """A channel was renamed, archived, deleted, or the bot was removed from it. The MAPPING and the
    WATERMARK follow the channel id, so nothing is lost on a rename; the other three mark the
    channel `gone` in state so the page can say why it no longer syncs. Filed documents stay -
    a channel closing does not un-say what was said in it (deletion is the uninstall's job)."""
    try:
        ch = ev.get("channel") if isinstance(ev.get("channel"), dict) else {"id": ev.get("channel")}
        cid = str(ch.get("id") or "")
        if not cid:
            return
        if kind == "member_left_channel":
            me = ((kb_slack.state().get("team") or {}).get("user_id") or "")
            if not me or ev.get("user") != me:
                return                       # somebody else left; the bot still reads the channel
        st = kb_slack.state()
        rec = st.setdefault("channels", {}).setdefault(cid, {})
        if kind == "channel_rename":
            name = ch.get("name") or ""
            rec["name"] = name
            cm = kb_slack.channel_map()
            if cid in cm and name:
                kb_slack.set_channel_client(cid, cm[cid].get("client", ""), name=name, by=cm[cid].get("by", ""))
        else:
            rec["gone"] = kind
            rec["gone_at"] = kb_store.now()
        kb_slack.save_state(st)
        _audit("slack_channel", cid, actor="slack", channel=rec.get("name", ""), note=kind, title=f"#{rec.get('name', cid)}")
    except Exception:                        # noqa: BLE001
        log.exception("slack: channel change %s failed", kind)


@bp.post("/slack/events")
def events():
    """The signature IS the auth, verified on the RAW body. Reply within Slack's 3 seconds: every
    real piece of work runs on a thread AFTER the response, and a message event is only a trigger
    to re-read that channel from history."""
    secret = kb_slack.signing_secret()
    if not secret:
        return jsonify(ok=False, error="not configured"), 503
    raw = request.get_data()
    if not kb_slack.verify_signature(dict(request.headers), raw, secret):
        log.warning("slack events: bad signature from %s", request.remote_addr)
        return jsonify(ok=False, error="bad signature"), 401
    try:
        payload = json.loads(raw)
    except Exception:                        # noqa: BLE001
        return jsonify(ok=False, error="bad json"), 400
    if payload.get("type") == "url_verification":
        return jsonify(challenge=payload.get("challenge", ""))
    if payload.get("type") != "event_callback":
        return jsonify(ok=True, ignored=True)
    ev = payload.get("event") or {}
    event_id = str(payload.get("event_id") or "")
    if _inbox_seen(event_id):
        return jsonify(ok=True, duplicate=True)
    b = _blocked("slack event ingest")
    if b:
        return b
    _inbox_keep(event_id, payload)
    kind = ev.get("type")
    if kind in ("app_uninstalled", "tokens_revoked"):
        threading.Thread(target=_purge_quietly, args=(kind,), name="slack-purge", daemon=True).start()
        return jsonify(ok=True, purge="started")
    if kind in ("channel_rename", "channel_archive", "channel_deleted", "member_left_channel", "channel_left"):
        threading.Thread(target=_channel_change_quietly, args=(kind, ev), name="slack-channel", daemon=True).start()
        return jsonify(ok=True, channel_change=kind)
    if kind == "message" and ev.get("channel") and kb_slack.enabled():
        known = (kb_slack.state().get("channels") or {}).get(ev["channel"]) or {}
        if known.get("is_private") and not kb_slack.ALLOW_PRIVATE:
            return jsonify(ok=True, ignored="private channel")
        ref = float(ev.get("thread_ts") or (ev.get("previous_message") or {}).get("ts") or ev.get("ts") or time.time())
        # Re-read from a little before the message (or its thread's parent) so the day/thread doc it
        # belongs to is rebuilt whole. `sync_in_progress` is NOT set: this is one channel, seconds.
        threading.Thread(target=_sync_quietly, args=(kb_slack.token(), ref - 60, "slack", ev["channel"]),
                         name="slack-event", daemon=True).start()
        return jsonify(ok=True, resync=ev["channel"])
    return jsonify(ok=True, ignored=kind)
