"""kb_fathom.py - ONE connected Fathom account's meetings into the knowledge base, filed to the right
client without a person having to say which (design docs/rag-assistant-design.md s7.1; K7-03 port).

Verified against developers.fathom.ai on 2026-09-14/15: REST base `https://api.fathom.ai/external/v1`,
header `X-Api-Key`; `GET /meetings` (cursor, created_after, include_transcript, include_summary);
transcript items `{speaker:{display_name, matched_calendar_invitee_email}, text, timestamp:'HH:MM:SS'}`;
webhooks deliver a Meeting object signed HMAC-SHA256 over `{webhook-id}.{webhook-timestamp}.{body}`,
Base64, as space-separated `v1,<b64>` entries in `webhook-signature`, secret `whsec_<base64>`,
5-minute timestamp tolerance. An API key is scoped to the USER who created it: Charles's key
returns Charles's meetings (decision 2026-09-15: his is the only connected account).

WHAT A MEETING BECOMES: one kb_store document, `kind=meeting`, `source=fathom`, in the client's
"Meetings" folder (agency-wide when it is about no client). The body is the summary FIRST - the
outcomes, which is what the Meetings folder promises - then the transcript, one line per speaker
turn headed `[HH:MM:SS]`, so a retrieved passage names its moment the way a PDF passage names its
page. kb_chunk splits it; kb_index ranks it with at most two passages per document, so a long
transcript cannot crowd the library. The raw meeting JSON is kept as the document's file.

THE ASSIGNMENT LADDER (decision 2026-09-14; internal rung reworked 2026-09-16) - top rung wins:
    0. internal   - no external invitee at all: a HINT, not a filing. The transcript still has to
                    prove the call is about the agency's or a client's work (rung 3, `work`).
    1. domain     - an external invitee's email domain matches exactly ONE client's declared domains
    2. memory     - kb_memory.match(): a person / recurring title confirmed on exactly one client
    3. evidence   - entity match against every client's live dashboard data + a corpus vote over
                    meetings already filed + ONE gemini-2.5-flash synthesis over the CLOSED list of
                    registry keys -> {client_key, confidence, why, work}
    4. human      - the Meetings queue: a person clicks Assign / Ignore, with rung 3's proposal
                    pre-selected.
FATHOM_AUTO_ASSIGN is the confidence at/above which rung 3 files without a click (default 0.95),
a client or agency-wide alike; a call the model says is not work at all (`work` false) always waits.
Rungs 1-2 always file. Every rung's signals travel with the decision and are logged.

Until assigned a meeting waits at <PREFIX>/fathom/unassigned/<recording_id>/{meeting,proposal}.json
- NOT as a document, so it is never retrievable before a person or a deterministic rung placed it.
"""
import os
import re
import json
import hmac
import time
import base64
import hashlib
import logging
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor

import requests

import kb_store
import kb_index
import kb_memory

log = logging.getLogger("kb_fathom")

API_BASE = "https://api.fathom.ai/external/v1"
SIGNATURE_TOLERANCE_S = 300
# THE RULE (Jerome, 2026-09-16): 95-100% sure files itself; anything less waits for a person.
# AUTO_ASSIGN is the model's threshold (rung 3); 1.01 would mean "never".
AUTO_ASSIGN = float(os.environ.get("FATHOM_AUTO_ASSIGN", "0.95"))
# Which SURE rungs (always 100%) may file without a click: "domain" (a declared client domain on the
# invite), "memory" (a person seen before on that client's calls). Default both. Set FATHOM_AUTO_FILE=""
# to make every meeting wait for a click (a sure rung then becomes a 100% guess in "Ready to confirm");
# a title on QUEUE_TITLES waits regardless. "internal" is NOT a sure rung any more (Jerome, 2026-09-16:
# an all-agency call "will only wait if the transcript also cannot prove it") - it is a hint to rung 3.
AUTO_FILE = frozenset(x.strip().lower() for x in os.environ.get("FATHOM_AUTO_FILE", "domain,memory").split(",")
                      if x.strip())
# Titles that ALWAYS wait for a person, whatever AUTO_FILE says. Word-bounded, case-insensitive.
QUEUE_TITLES = [x.strip() for x in (os.environ.get("FATHOM_QUEUE_TITLES") or
                "1:1,1-1,one on one,one-on-one,interview,hr,performance review,personal,salary,payroll,catch-up,catch up").split(",")
                if x.strip()]
_QUEUE_TITLE_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t.lower()) for t in QUEUE_TITLES) + r")(?![a-z0-9])")


def watched_title(meeting):
    """The watch-list word the title matched, or ''."""
    m = _QUEUE_TITLE_RE.search((meeting.get("title") or meeting.get("meeting_title") or "").lower())
    return m.group(1) if m else ""
# How much of a corpus vote counts as a signal rather than a coincidence. See corpus_vote.
VOTE_MIN = int(os.environ.get("FATHOM_VOTE_MIN", "3"))        # fewer passages than this proves nothing
VOTE_SHARE = float(os.environ.get("FATHOM_VOTE_SHARE", "0.6"))  # and one client must clearly lead
CLASSIFY_MODEL = os.environ.get("FATHOM_CLASSIFY_MODEL", "gemini-2.5-flash")
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

AGENCY = ""                    # kb_store's "agency-wide": the empty client key
FOLDER = "Meetings"            # kb_routes.CLIENT_FOLDERS' third shelf
SOURCE = "fathom"
KIND = "meeting"
_UNASSIGNED = "fathom/unassigned"
_STATE = "fathom/state.json"
MAX_TRANSCRIPT_CHARS = 350_000  # under kb_store.MAX_BODY_CHARS with the summary in front


def enabled():
    return bool(os.environ.get("FATHOM_API_KEY"))


# --- webhook -------------------------------------------------------------------------------------

def verify_signature(headers, body, secret, now=None):
    """True iff one `v1,<b64>` entry in webhook-signature is HMAC-SHA256(secret, '{id}.{ts}.{body}')
    and the timestamp is within tolerance. Constant-time compare. `body` = the RAW request bytes."""
    if not secret:
        return False
    h = {k.lower(): v for k, v in (headers or {}).items()}
    wid, ts, sig = h.get("webhook-id"), h.get("webhook-timestamp"), h.get("webhook-signature")
    if not (wid and ts and sig):
        return False
    try:
        if abs((now or time.time()) - int(ts)) > SIGNATURE_TOLERANCE_S:
            return False
    except ValueError:
        return False
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    signed = f"{wid}.{ts}.".encode("utf-8") + raw
    sec = secret.encode("utf-8")
    if sec.startswith(b"whsec_"):            # Svix-style: base64 after the prefix
        try:
            sec = base64.b64decode(sec[6:])
        except Exception:                    # noqa: BLE001 - then it was a raw secret after all
            pass
    expected = base64.b64encode(hmac.new(sec, signed, hashlib.sha256).digest()).decode()
    for part in sig.split():
        v, _, given = part.partition(",")
        if v == "v1" and hmac.compare_digest(given, expected):
            return True
    return False


# --- meeting -> document -------------------------------------------------------------------------

def recording_id(meeting):
    return str(meeting.get("recording_id") or meeting.get("id") or "").strip()


def doc_id(meeting):
    """`fathom-<recording_id>`: stable, so a re-delivered webhook re-indexes rather than duplicates.
    Sanitised to kb_store's id alphabet."""
    rid = re.sub(r"[^A-Za-z0-9_-]", "-", recording_id(meeting))[:56]
    return f"fathom-{rid or 'x'}"


def meeting_title(meeting):
    t = (meeting.get("title") or meeting.get("meeting_title") or "").strip()
    when = (meeting.get("recording_start_time") or meeting.get("created_at") or "")[:10]
    if t and when:
        return f"{t} ({when})"
    return t or f"Fathom meeting {recording_id(meeting)}"


def summary_text(meeting):
    """Fathom's `default_summary` is an OBJECT on the live API - {template_name, markdown_formatted}
    (found on the first real sync, 2026-09-16; the docs' examples and our fixtures had a string).
    Accept both, and never str() a dict into the document body."""
    s = meeting.get("default_summary")
    if isinstance(s, dict):
        s = s.get("markdown_formatted") or s.get("markdown_formatted_summary") or s.get("text") or ""
    return str(s or "").strip()


_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def clean_summary(text):
    """Fathom wraps EVERY summary line in a link back to the recording at that second. Good in Fathom,
    noise in a document (and in every chunk the search sees). Keep the words, drop the links; the
    document carries one 'Open in Fathom' link instead."""
    return _MD_LINK.sub(r"\1", text or "").strip()


def transcript_turns(meeting, max_chars=MAX_TRANSCRIPT_CHARS):
    """Fathom emits one line per utterance ('Yan.' / 'Yan, yan.' each with its own timestamp).
    Merge consecutive lines by the same speaker into one turn, stamped with the turn's first time.
    -> (lines, cut)."""
    turns, cut = [], False
    for it in meeting.get("transcript") or []:
        text = (it.get("text") or "").strip()
        if not text:
            continue
        sp = it.get("speaker") or {}
        name = (sp.get("display_name") or "").strip() if isinstance(sp, dict) else str(sp)
        ts = (it.get("timestamp") or "").strip()
        if turns and turns[-1][1] == name:
            turns[-1][2].append(text)
        else:
            turns.append([ts, name, [text]])
    lines, used = [], 0
    for ts, name, texts in turns:
        line = (f"[{ts}] " if ts else "") + (f"{name}: " if name else "") + " ".join(texts)
        if used + len(line) > max_chars:
            cut = True
            break
        lines.append(line)
        used += len(line) + 1
    return lines, cut


def meeting_body(meeting, max_transcript_chars=MAX_TRANSCRIPT_CHARS):
    """Summary first (outcomes, plain text, one link to the recording), then the transcript as one
    `[HH:MM:SS] Speaker: ...` line per speaker TURN. A cut is declared in the text (the kb_extract
    rule)."""
    parts = []
    summary = clean_summary(summary_text(meeting))
    link = meeting.get("share_url") or meeting.get("url") or ""
    if summary:
        parts.append("## Summary\n" + (f"Open in Fathom: {link}\n\n" if link else "") + summary)
    lines, cut = transcript_turns(meeting, max_transcript_chars)
    if lines:
        parts.append("## Transcript\n" + "\n".join(lines))
    if cut:
        parts.append("[Import note: this transcript was cut to fit. Anything past this point is "
                     "unknown, not absent.]")
    if not parts:
        parts.append(meeting_title(meeting) + " (no summary or transcript captured)")
    return "\n\n".join(parts)


def invitees(meeting):
    return [{"email": i.get("email"), "domain": i.get("email_domain"), "external": kb_memory.is_external(i),
             "name": i.get("name")} for i in (meeting.get("calendar_invitees") or [])]


def _duration_min(m):
    try:
        s = _dt.datetime.fromisoformat(str(m.get("recording_start_time")).replace("Z", "+00:00"))
        e = _dt.datetime.fromisoformat(str(m.get("recording_end_time")).replace("Z", "+00:00"))
        return int((e - s).total_seconds() // 60)
    except Exception:                        # noqa: BLE001
        return None


def already_indexed(meeting):
    """The client key the meeting is already filed under, or None. Reads the doc object (one GET)."""
    doc = kb_store.read_doc(doc_id(meeting))
    if not doc or doc.get("archived"):
        return None
    return doc.get("client") or AGENCY


def index_meeting(meeting, client_key, assigned_by, evidence=None, actor="", skip_learning=None):
    """File one meeting as a kb document under `client_key` ("" = agency-wide), keep the raw JSON as
    its file, LEARN from it when the assignment was deterministic or human, and clear the queue
    entry. `skip_learning` = the items the person unticked on the card (see kb_memory.teaches).
    Returns the document meta (kb_store.doc_meta + chunks)."""
    rid = recording_id(meeting)
    ck = kb_store.client_key(client_key)
    body = meeting_body(meeting)
    recorded_by = (meeting.get("recorded_by") or {}).get("email", "") if isinstance(meeting.get("recorded_by"), dict) else ""
    doc = kb_store.make_doc(title=meeting_title(meeting), body=body, kind=KIND, folder=FOLDER,
                            source=SOURCE, owner=actor or recorded_by or "fathom",
                            filename="meeting.json", mime="application/json",
                            size_bytes=len(json.dumps(meeting)), doc_id=doc_id(meeting), client=ck)
    # Fathom-specific facts ride on the document object; kb_store.doc_meta ignores keys it does not
    # know, so nothing in the index changes shape.
    doc["fathom"] = {"recording_id": rid, "url": meeting.get("url") or meeting.get("share_url") or "",
                     "recorded_at": meeting.get("recording_start_time") or meeting.get("created_at") or "",
                     "duration_min": _duration_min(meeting), "invitees": invitees(meeting),
                     "assigned_by": assigned_by, "assignment_evidence": list(evidence or [])[:20]}
    try:
        kb_store.write_file(doc["id"], "meeting.json", json.dumps(meeting, ensure_ascii=False).encode("utf-8"),
                            content_type="application/json")
    except Exception:                        # noqa: BLE001 - the text is the searchable part
        log.exception("fathom: could not keep the raw meeting for %s", rid)
    rep = kb_index.reindex_document(doc)
    if assigned_by in ("domain", "human", "memory") and ck != AGENCY:
        try:
            kb_memory.learn(ck, meeting, doc["id"],
                            patterns=[e.split("campaign ", 1)[1].split('"')[1] for e in (evidence or [])
                                      if e.startswith('campaign "')],
                            skip=skip_learning)
        except Exception:                    # noqa: BLE001 - memory mirrors; the document is filed
            log.exception("fathom: memory.learn failed for %s", rid)
    drop_unassigned(rid)
    meta = kb_store.doc_meta(doc)
    meta.update(chunks=rep.get("chunks", 0), semantic=rep.get("semantic", False),
                assigned_by=assigned_by, recording_id=rid)
    return meta


def rebuild_document(rid):
    """Re-derive a filed meeting's TEXT from the raw meeting.json kept as its file, keeping id,
    client, folder and every other header. For documents filed before a body-format change (the
    first real sync filed one with the summary's raw object in it). -> doc meta, or None."""
    did = doc_id({"recording_id": rid})
    doc = kb_store.read_doc(did)
    if not doc:
        return None
    data, _ct = kb_store.read_file(did, "meeting.json")        # -> (bytes, content_type) or (None, None)
    if not data:
        return None
    meeting = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    doc["body"] = meeting_body(meeting)
    doc["title"] = meeting_title(meeting)
    rep = kb_index.reindex_document(doc)
    meta = kb_store.doc_meta(doc)
    meta.update(chunks=rep.get("chunks", 0), semantic=rep.get("semantic", False), recording_id=str(rid))
    return meta


# --- the queue -----------------------------------------------------------------------------------

def store_unassigned(meeting, proposal=None):
    """Park a meeting no deterministic rung placed. Idempotent on recording_id."""
    rid = recording_id(meeting)
    if not rid:
        raise ValueError("meeting has no recording_id")
    kb_store._write_json(f"{_UNASSIGNED}/{rid}/meeting.json", meeting)
    if proposal is not None:
        kb_store._write_json(f"{_UNASSIGNED}/{rid}/proposal.json", proposal)
    return rid


def list_unassigned():
    """-> [{recording_id, title, created_at, duration_min, invitees[], summary, proposal{},
    will_learn{people, domains, title}}], newest first."""
    prefix = f"{kb_store.PREFIX}/{_UNASSIGNED}/"
    seen = {}
    for blob in kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=prefix):
        rest = blob.name[len(prefix):].split("/")
        if len(rest) != 2:
            continue
        seen.setdefault(rest[0], {})[rest[1]] = blob
    def _read(rid, files):
        if "meeting.json" not in files:
            return None
        try:
            m = json.loads(files["meeting.json"].download_as_bytes().decode("utf-8"))
        except Exception:                    # noqa: BLE001
            return None
        prop = {}
        if "proposal.json" in files:
            try:
                prop = json.loads(files["proposal.json"].download_as_bytes().decode("utf-8"))
            except Exception:                # noqa: BLE001
                prop = {}
        return {"recording_id": rid, "title": m.get("title") or m.get("meeting_title") or "(untitled)",
                "created_at": m.get("created_at") or m.get("recording_start_time"),
                "duration_min": _duration_min(m), "invitees": invitees(m),
                "summary": summary_text(m)[:600], "proposal": prop,
                "will_learn": kb_memory.teaches(m)}
    # Two GETs per queued meeting; sequentially that is ~20 s for a dozen from a laptop, so read them
    # side by side (2026-09-15, found when Jerome asked to see a full queue).
    with ThreadPoolExecutor(max_workers=8) as ex:
        out = [r for r in ex.map(lambda kv: _read(*kv), list(seen.items())) if r]
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def load_unassigned(rid):
    return kb_store._read_json(f"{_UNASSIGNED}/{rid}/meeting.json", default=None)


def load_proposal(rid):
    """The guess a queued meeting is waiting on, or {}. Read by the audit record so a person's
    decision can be logged NEXT TO what the system had proposed - which is what makes "did the
    human agree?" answerable later."""
    return kb_store._read_json(f"{_UNASSIGNED}/{rid}/proposal.json", default={}) or {}


def drop_unassigned(rid):
    prefix = f"{kb_store.PREFIX}/{_UNASSIGNED}/{rid}/"
    for blob in kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=prefix):
        blob.delete()


# A sync that never finished must not look like one that is still running. Cloud Run can stop an
# instance mid-sync (a deploy, a scale-down, CPU throttled after the response), and `_sync_quietly`
# is the only thing that clears the flag - so the flag survives the work that was meant to clear it.
SYNC_STALE_S = 1800


def state():
    return kb_store._read_json(_STATE, default={}) or {}


def syncing(st=None):
    """True only while a sync is plausibly still running.

    🔴 THE FLAG ALONE IS NOT THE ANSWER, and reading it as if it were has a visible cost: the
    Meetings page re-polls every 5 seconds while a sync is "in progress" and REBUILDS the queue on
    each poll, which closes any card a person has opened. Found live 2026-09-17 with a flag 142
    minutes stale - the page was unusable for reading a card's evidence, and it looked like a bug in
    the expander. The 30-minute rule already existed in the sync route; it just was not shared."""
    st = state() if st is None else st
    if not st.get("sync_in_progress"):
        return False
    try:
        started = float(st.get("sync_started_ts") or 0)
    except (TypeError, ValueError):
        return False
    return (time.time() - started) < SYNC_STALE_S


def save_state(st):
    kb_store._write_json(_STATE, st)


# --- the ladder ----------------------------------------------------------------------------------

def external_domains(meeting):
    return sorted({(i.get("email_domain") or (i.get("email") or "").rsplit("@", 1)[-1]).lower()
                   for i in (meeting.get("calendar_invitees") or [])
                   if kb_memory.is_external(i) and (i.get("email_domain") or i.get("email"))} - {""})


def rung_domain(meeting, client_domains):
    """`client_domains` = {client_key: ["cloudflare.com", ...]} (kb_memory.all_client_domains).
    Exactly one client matched -> ("assign", key, evidence); several -> ("hint", {..}, lines);
    none -> (None, None, [])."""
    doms = external_domains(meeting)
    hits = {}
    for ck, lst in (client_domains or {}).items():
        matched = sorted(d for d in doms if d in {x.lower() for x in (lst or [])})
        if matched:
            hits[ck] = [f"invitee domain {d}" for d in matched]
    if not hits:
        return None, None, []
    if len(hits) == 1:
        ck, ev = next(iter(hits.items()))
        return "assign", ck, ev
    return "hint", hits, [f"{ck}: {', '.join(ev)}" for ck, ev in hits.items()]


def entity_match(meeting, entities_by_client, max_hits=5):
    """`entities_by_client` = {client_key: {"campaign names", ...}} harvested from each client's live
    dashboard data by the caller. -> {client_key: [evidence]} for exact (case-insensitive) hits of a
    client's entity in the meeting text. Entities under 6 chars or shared by 2+ clients are ignored."""
    text = " ".join([meeting.get("title") or "", summary_text(meeting)] +
                    [(t.get("text") or "") for t in (meeting.get("transcript") or [])]).lower()
    owners = {}
    for ck, ents in (entities_by_client or {}).items():
        for e in ents or ():
            e2 = str(e).strip()
            if len(e2) >= 6:
                owners.setdefault(e2.lower(), set()).add(ck)
    hits = {}
    for ent, cks in owners.items():
        if len(cks) != 1 or ent not in text:
            continue
        ck = next(iter(cks))
        if len(hits.get(ck, [])) < max_hits:
            hits.setdefault(ck, []).append(f'campaign "{ent}" found in {ck}\'s dashboard data')
    return hits


def corpus_vote(meeting, limit=20):
    """Search the library with the meeting's opening and tally the clients of the Fathom meetings
    that come back. Only FILED meetings exist as documents, and every filed meeting was placed by a
    deterministic rung or a person (auto-assign is off), so the vote is over confirmed placements
    by construction. -> ({client: n}, [evidence]); ({}, []) when nothing votes or search fails."""
    probe = " ".join(filter(None, [meeting.get("title"), summary_text(meeting)] +
                            transcript_turns(meeting, max_chars=4000)[0]))[:6000]
    if not probe.strip():
        return {}, []
    try:
        res = kb_index.search(probe, limit=limit)
        metas = dict(kb_index.all_meta(include_archived=False))        # {doc_id: meta}
    except Exception:                        # noqa: BLE001 - the vote is advisory
        log.exception("fathom: corpus vote failed")
        return {}, []
    tally = {}
    for ex in res.get("excerpts") or []:
        m = metas.get(ex.get("document_id"))
        if not m or m.get("kind") != KIND or m.get("source") != SOURCE:
            continue
        ck = m.get("client") or ""
        if ck:
            tally[ck] = tally.get(ck, 0) + 1
    if not tally:
        return {}, []
    total = sum(tally.values())
    top = max(tally, key=tally.get)

    # 🔴 A THIN OR SPLIT VOTE IS NOISE, AND REPORTING IT AS EVIDENCE IS WORSE THAN SAYING NOTHING.
    # Measured on the first real sync (2026-09-17): a daily stand-up produced "1 of 1 similar
    # passages are from cloudflare meetings" and the model filed it to a client at 95%+. Two of
    # three stand-ups landed on the wrong client that way. The model cannot tell a one-passage
    # coincidence from a real signal - the EVIDENCE LINE reads identically either way - so the
    # filtering has to happen here, where the counts are.
    if total < VOTE_MIN or tally[top] / total < VOTE_SHARE:
        spread = ", ".join(sorted(tally)) if len(tally) > 1 else top
        # Say what was seen WITHOUT naming a winner: a meeting touching several clients is a real
        # signal that it belongs to NONE of them, which is the opposite conclusion.
        return tally, [f"similar passages come from several clients ({spread}) - no clear match"] if len(tally) > 1 else []
    return tally, [f"{tally[top]} of {total} similar passages are from {top} meetings"]


def synthesise(meeting, candidates, evidence_lines, _post=None, internal=False):
    """One gemini-2.5-flash call over the closed candidate list + the evidence -> {client_key,
    confidence, why, work}. A key outside the list is rejected (-> agency-wide, confidence 0).
    `work` is the model's answer to "is this call about the agency's or a client's business at
    all?" - it is what lets an all-agency call file itself as agency-wide (True) or wait (False)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not candidates:
        # Name the reason: on 2026-09-15 a test rig showed "classifier unavailable" and nobody could
        # tell a missing key from an empty client list without reading the code.
        why = "classifier unavailable: " + ("no GEMINI_API_KEY in this process" if not key else "no candidate clients")
        log.warning("fathom synthesise: %s", why)
        return {"client_key": AGENCY, "confidence": 0.0, "why": why, "work": False}
    # Speaker TURNS (transcript_turns), not raw utterances: the same 12k characters carry roughly
    # three times the conversation, and the transcript is the strongest evidence there is.
    excerpt = "\n".join(transcript_turns(meeting, max_chars=12000)[0])
    prompt = (
        "You assign a recorded agency meeting to ONE client. Choose ONLY from the candidate keys "
        "below, or '' (empty string) if the meeting is about the agency itself, several clients at "
        "once, or no client. Return JSON {\"client_key\": str, \"confidence\": number 0-1, \"why\": str, "
        "\"work\": bool}. `work` is true when the conversation is about the agency's business or a "
        "client's business (campaigns, dashboards, data, briefs, pipeline, staffing FOR that work); "
        "false when it is personal, social, HR, or otherwise not something the agency would file. "
        "Confidence 0.9+ for a client key only when the transcript names the client or its campaigns "
        "unambiguously; confidence 0.9+ for '' only when the discussion is clearly the agency's own "
        "work and no single client.\n\n"
        # 🔴 The rule these two lines encode, learned from the first real sync (2026-09-17): a stand-up
        # that walks through five clients in ten minutes was filed to ONE of them at 95%+, three times.
        # A call ABOUT several clients belongs to none of them, and that has to be said, because
        # "mentions Cloudflare" and "is about Cloudflare" look identical to a classifier.
        "A meeting that moves between SEVERAL clients - a stand-up, a weekly kick-off, a pipeline "
        "review - belongs to NO single client. Return '' for it, with high confidence. Choose a "
        "client ONLY when that client is what the meeting is FOR, not merely one of several "
        "mentioned in passing. If you are choosing between two or more clients, the answer is ''.\n\n"
        + ("EVERYONE ON THIS CALL IS FROM THE AGENCY (no client invitee). Decide from the transcript "
           "whether it is agency work ('' with high confidence), one client's work (that key), or not "
           "work at all (work=false).\n\n" if internal else "")
        + "CANDIDATES:\n" + "\n".join(f"- {c['key']}: {c['name']}" + (f" - {c['desc']}" if c.get("desc") else "")
                                      for c in candidates) +
        "\n\nEVIDENCE ALREADY GATHERED:\n" + ("\n".join(f"- {e}" for e in evidence_lines) or "- none") +
        f"\n\nTITLE: {meeting.get('title') or ''}\nSUMMARY: {summary_text(meeting)[:3000]}\n"
        f"TRANSCRIPT (start):\n{excerpt}")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 400, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    post = _post or (lambda b: requests.post(GEMINI.format(model=CLASSIFY_MODEL),
                                             headers={"x-goog-api-key": key, "content-type": "application/json"},
                                             json=b, timeout=90))
    try:
        r = post(body)
        parts = (((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        txt = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        out = json.loads(txt)
    except Exception as e:                   # noqa: BLE001
        return {"client_key": AGENCY, "confidence": 0.0, "why": f"classifier error: {type(e).__name__}", "work": False}
    allowed = {c["key"] for c in candidates} | {AGENCY}
    ck = kb_store.client_key(str(out.get("client_key") or ""))
    if str(out.get("client_key") or "") and ck not in allowed:
        return {"client_key": AGENCY, "confidence": 0.0, "why": f"model returned unknown key {out.get('client_key')!r}",
                "work": False}
    try:
        conf = max(0.0, min(1.0, float(out.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    # A named client IS work; otherwise take the model's word, defaulting to False when it is silent.
    work = bool(ck) or out.get("work") is True
    return {"client_key": ck, "confidence": conf, "why": str(out.get("why") or "")[:300], "work": work}


def classify(meeting, client_domains, memories, candidates, entities_by_client=None, auto_assign=None,
             _post=None, vote=corpus_vote, auto_file=None):
    """Run the ladder. -> {"decision": "assign"|"queue", "client_key", "assigned_by", "confidence",
    "evidence": [..], "proposal": {...}}. Deterministic rungs assign; rung 3 assigns only at/above
    `auto_assign` (default FATHOM_AUTO_ASSIGN = never in the pilot); else queued with the proposal."""
    threshold = AUTO_ASSIGN if auto_assign is None else auto_assign
    auto_file = AUTO_FILE if auto_file is None else frozenset(auto_file)
    watched = watched_title(meeting)

    def sure(client_key, by, evidence, why):
        """A rung that is CERTAIN. It files only if that rung is in `auto_file` AND the title is not
        on the watch-list; otherwise it is a 100% guess for a person (the pilot default)."""
        if by in auto_file and not watched:
            return {"decision": "assign", "client_key": client_key, "assigned_by": by, "confidence": 1.0,
                    "evidence": evidence, "proposal": None}
        if watched:
            why += f" - the title matches the watch-list ('{watched}'), so it always waits for a person"
        return {"decision": "queue", "client_key": None, "assigned_by": None, "confidence": 1.0,
                "evidence": evidence, "proposal": {"client_key": client_key, "confidence": 1.0, "why": why,
                                                   "evidence": evidence, "sure_by": by}}

    # rung 0: no external invitee at all -> a HINT for rung 3, never a filing on its own. The
    # invite list says who was there; only the transcript says what it was about (Jerome,
    # 2026-09-16: an internal call "will only wait if the transcript also cannot prove it").
    inv = meeting.get("calendar_invitees") or []
    internal = bool(inv) and not any(kb_memory.is_external(i) for i in inv)
    hints = ["no external invitee - internal meeting"] if internal else []
    # rung 1: declared domain
    kind, val, ev = rung_domain(meeting, client_domains)
    if kind == "assign":
        return sure(val, "domain", ev, "An invitee is from a declared client email domain: " + "; ".join(ev)[:200])
    hints += list(ev) if kind == "hint" else []
    # rung 2: memory
    mkind, mval, mev = kb_memory.match(meeting, memories or {})
    if mkind == "assign" and kind != "hint":
        return sure(mval, "memory", mev, "A person or recurring title the system has seen on this client's calls before: " + "; ".join(mev)[:200])
    if mkind:
        hints += mev if mkind == "hint" else [f"{mval}: {e}" for e in mev]
    # rung 3: evidence bundle
    for ck, lines in entity_match(meeting, entities_by_client or {}).items():
        hints += lines
    tally, kev = vote(meeting)
    hints += kev
    prop = synthesise(meeting, candidates, hints, _post=_post, internal=internal)
    prop["evidence"] = hints
    # THE RULE: 95%+ files itself, a client or agency-wide alike; the model decides from the
    # transcript, the vote and the hints. The one thing that never files is a call the model says
    # is not work at all (work=False) - that waits for a person, and the card says why.
    names_client = prop["client_key"] in {c["key"] for c in candidates}
    agency_work = prop["client_key"] == AGENCY and prop.get("work") is True
    if not prop.get("work") and prop["confidence"] > 0:
        prop["why"] = "The transcript does not read as agency or client work - " + prop["why"]
    if prop["confidence"] >= threshold and (names_client or agency_work) and not watched:
        return {"decision": "assign", "client_key": prop["client_key"], "assigned_by": "model",
                "confidence": prop["confidence"], "evidence": hints, "proposal": prop}
    return {"decision": "queue", "client_key": None, "assigned_by": None, "confidence": prop["confidence"],
            "evidence": hints, "proposal": prop}


# --- pull ----------------------------------------------------------------------------------------

def fetch_meetings(api_key, created_after=None, page_limit=50, _get=None):
    """GET /meetings with transcript + summary, following `next_cursor`. Generator of meeting dicts."""
    get = _get or (lambda url, params: requests.get(url, params=params, headers={"X-Api-Key": api_key}, timeout=60))
    params = {"include_transcript": "true", "include_summary": "true"}
    if created_after:
        params["created_after"] = created_after
    cursor, pages = None, 0
    while pages < page_limit:
        if cursor:
            params["cursor"] = cursor
        r = get(f"{API_BASE}/meetings", params)
        if r.status_code != 200:
            raise RuntimeError(f"Fathom HTTP {r.status_code}: {r.text[:200]}")
        j = r.json() or {}
        for m in j.get("items") or j.get("meetings") or j.get("data") or []:
            yield m
        cursor = j.get("next_cursor") or j.get("cursor")
        pages += 1
        if not cursor:
            break
