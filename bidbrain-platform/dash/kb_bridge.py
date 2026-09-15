"""kb_bridge.py - the one place the per-dashboard staff assistant reads the knowledge base (K7-06).

Two AI surfaces, two sources, deliberately separate until now: the dashboard assistant holds the
NUMBERS (live data.json + lineage + notes), the knowledge base at /kb holds the WORDS (plans, briefs,
meetings, the playbook, corrections). This module lets the dashboard assistant read the words for
ITS client - and nothing else changes: /kb still cannot see a dashboard, and the customer assistant
does not come through here.

WHO. `retrieve()` is only ever called for a session that passed BOTH gates - `_internal_allowed`
(may see this dashboard's staff widget) AND `_kb_allowed` (may open /kb) - decided in main.py. So an
outside agency that shares a dashboard gets no library passages, and neither does an internal
agency Ian has not admitted to /kb. Ships dark behind `KNOWLEDGE_RETRIEVAL=on`.

WHAT. `kb_index.search(q, client=<key>)`, which is THAT client plus agency-wide and never another
client (kb_index.doc_ids_for_client). The query is shaped, not passed through: a short follow-up
("and for Q3?", "why?") is meaningless on its own, so it is prefixed with the previous question.
Passages come back as the assistant's numbered [n] context; verified corrections are labelled so
the model can say an answer follows a colleague's fix; and when meaning search was unavailable the
context says so, so the model can say "I searched by wording only" rather than "there is nothing".

The question is logged into the knowledge base's own activity stream (kind "question", source
"dashboard"), so Ian's Observability page counts dashboard questions beside /kb ones.
"""
import logging
import re

import kb_index
import kb_store
import kb_activity

log = logging.getLogger("kb_bridge")

LIMIT = 6                       # passages handed to the model; his Ask panel uses 8, a dashboard turn already carries data.json
SNIPPET_CHARS = 600             # what a click on [n] shows in the widget
MAX_PASSAGE_CHARS = 2_500       # per passage in the prompt; a guard, not a budget
SHORT_QUERY_WORDS = 5
_FOLLOW_UP = re.compile(r"^\s*(and|also|what about|how about|why|so|then|but|ok|okay|same|those|that|it|this)\b", re.I)


def shape_query(messages):
    """The text to search for. The last user message, prefixed with the previous user message when
    the last one cannot stand alone (short, or opens like a follow-up)."""
    users = [m.get("content", "") for m in (messages or []) if m.get("role") == "user" and (m.get("content") or "").strip()]
    if not users:
        return ""
    q = users[-1].strip()
    if len(users) > 1 and (len(q.split()) < SHORT_QUERY_WORDS or _FOLLOW_UP.match(q)):
        q = users[-2].strip()[:400] + " " + q
    return q[:1_000]


def retrieve(client, messages, actor=""):
    """-> {"passages": [...], "semantic": bool, "semantic_error": str, "query": str, "searched": n}
    or None when there is nothing to search with. Never raises: the assistant answers from the
    dashboard alone if the library is unreachable, and the failure is logged."""
    q = shape_query(messages)
    if not q:
        return None
    ck = kb_store.client_key(client)
    try:
        res = kb_index.search(q, limit=LIMIT, client=ck)
    except Exception:                        # noqa: BLE001 - retrieval is additive, never blocking
        log.exception("kb_bridge: search failed for %s", client)
        return {"passages": [], "semantic": False, "semantic_error": "library unreachable", "query": q, "searched": 0}
    passages = []
    for i, ex in enumerate(res.get("excerpts") or [], 1):
        passages.append({
            "n": i, "doc_id": ex.get("document_id"), "title": ex.get("title") or "", "folder": ex.get("folder") or "",
            "kind": ex.get("kind") or "", "trust": ex.get("trust") or kb_store.TRUST_STANDARD,
            "owner": ex.get("owner") or "", "ord": ex.get("ord"),
            "text": (ex.get("passage") or "").strip()[:MAX_PASSAGE_CHARS],
            "found_by": ex.get("found_by") or [],
        })
    try:
        kb_activity.log_event("question", actor=actor, source="dashboard", client=ck, question=q[:500],
                              passages=len(passages), semantic=bool(res.get("semantic")), outcome=res.get("outcome") or "")
    except Exception:                        # noqa: BLE001
        pass
    return {"passages": passages, "semantic": bool(res.get("semantic")), "semantic_error": res.get("semantic_error") or "",
            "query": q, "searched": int(res.get("documents_searched") or 0)}


VISIBILITY_FIELD = "visibility"          # on a document; "client" = the client may be shown it
VISIBILITY_CLIENT = "client"


def retrieve_for_client(client, messages):
    """The CLIENT ASSISTANT's read: the same client + agency-wide search, then ONLY documents a
    person marked client-visible - and never a meeting, whatever it is marked.

    🔴 THE FIELD DOES NOT EXIST YET. Ian's documents carry no `visibility`; adding it (with its
    default "internal") is the held K7-02 change. Until it lands every document fails this filter
    and the client assistant retrieves NOTHING - by construction, not by configuration. Nothing here
    changes when the field arrives; that is the point of filtering on it now.
    """
    q = shape_query(messages)
    if not q:
        return None
    ck = kb_store.client_key(client)
    try:
        res = kb_index.search(q, limit=LIMIT * 2, client=ck)
        metas = {m["id"]: m for m in kb_index.all_meta(include_archived=False)}
    except Exception:                        # noqa: BLE001
        log.exception("kb_bridge: client search failed for %s", client)
        return {"passages": [], "semantic": False, "semantic_error": "library unreachable", "query": q, "searched": 0}
    passages = []
    for ex in res.get("excerpts") or []:
        m = metas.get(ex.get("document_id")) or {}
        if m.get(VISIBILITY_FIELD) != VISIBILITY_CLIENT or m.get("kind") == "meeting":
            continue
        passages.append({
            "n": len(passages) + 1, "doc_id": ex.get("document_id"), "title": ex.get("title") or "",
            "folder": "", "kind": ex.get("kind") or "", "trust": kb_store.TRUST_STANDARD, "owner": "",
            "ord": ex.get("ord"), "text": (ex.get("passage") or "").strip()[:MAX_PASSAGE_CHARS],
            "found_by": ex.get("found_by") or [],
        })
        if len(passages) >= LIMIT:
            break
    return {"passages": passages, "semantic": bool(res.get("semantic")), "semantic_error": res.get("semantic_error") or "",
            "query": q, "searched": int(res.get("documents_searched") or 0), "audience": "client"}


def render_context(ret):
    """The labelled block for systemInstruction. Numbered so the model cites [n]; verified corrections
    say so; an unavailable meaning search is stated (the kb rule: a gap must never read as absence)."""
    if ret is None:
        return ""
    client_aud = (ret.get("audience") == "client")
    head = ("=== RETRIEVED CONTEXT (documents shared with you; cite [n] when you rely on one) ===" if client_aud
            else "=== LIBRARY (the agency's written record for this client + agency-wide; cite [n] when you rely on one) ===")
    lines = [head]
    if not ret.get("semantic"):
        why = ret.get("semantic_error") or "meaning search unavailable"
        lines.append(f"(searched by WORDING ONLY - {why}. If nothing below answers the question, say the "
                     f"library was searched by wording only, not that it holds nothing.)")
    if not ret.get("passages"):
        lines.append("(nothing in the library bears on this question)")
        return "\n".join(lines)
    for p in ret["passages"]:
        where = " · ".join(x for x in (p.get("folder"), p.get("title")) if x) or "untitled"
        if p.get("kind") and not client_aud:
            where += f" ({p['kind']})"
        if p.get("trust") == kb_store.TRUST_VERIFIED and not client_aud:
            who = f" by {kb_store.display_actor(p.get('owner'))}" if p.get("owner") and hasattr(kb_store, "display_actor") else ""
            where += f" - VERIFIED CORRECTION{who}: this outranks the document it corrects; say so when you use it"
        lines.append(f"[{p['n']}] {where}\n{p['text']}\n")
    return "\n".join(lines)


def sources_for(ret):
    """What the widget renders under a reply: [{n, title, folder, kind, trust, doc_id, snippet}]."""
    out = []
    for p in (ret or {}).get("passages") or []:
        txt = p.get("text") or ""
        out.append({"n": p["n"], "title": p.get("title"), "folder": p.get("folder"), "kind": p.get("kind"),
                    "trust": p.get("trust"), "doc_id": p.get("doc_id"),
                    "snippet": txt[:SNIPPET_CHARS] + ("…" if len(txt) > SNIPPET_CHARS else "")})
    return out
