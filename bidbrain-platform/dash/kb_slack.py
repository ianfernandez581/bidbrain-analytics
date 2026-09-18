"""kb_slack.py - Slack channels into the knowledge base (sibling of kb_fathom.py; 2026-09-17).

A bot user is invited to a channel; that invite is the whole scope control (nothing is configured
in code). The channel's messages become documents under the client the channel belongs to:

    one document per THREAD            slack-<channel>-t<parent ts>      "the first line of the thread"
    one document per CHANNEL-DAY       slack-<channel>-d<YYYY-MM-DD>     "#geocon - 2026-09-17"
    (the day doc holds the unthreaded messages; a thread is one conversation and stands alone)

🔴 EVENTS ARE TRIGGERS, HISTORY IS THE TRUTH. A Slack event (a new message, an edit, a delete) only
says "this conversation changed"; the document is always rebuilt from `conversations.history` /
`conversations.replies`, never patched from the event body. So an edited message reads as edited,
a deleted message is simply no longer there after the rebuild (Developer Policy: honour deletion),
and "Sync now" and the webhook share ONE code path. The raw event is kept in slack/inbox for the
audit trail, not as a source of text.

FILING. A channel a person has mapped to a client (slack/channels.json - the declared signal, like
a client's email domains) files with assigned_by="channel" and no model call. An unmapped channel
goes through the SAME ladder as a meeting (kb_fathom.classify over a meeting-shaped view of the
conversation): memory -> evidence -> one synthesis -> file at 95%+ or wait in the queue. Nothing
about a channel's NAME is a rule.

WHAT NEVER HAPPENS HERE: no direct messages (no im:* scopes), no posting (no chat:write), no text
sent to any model other than the ladder's classifier, no storage of anything from a channel the bot
was not invited to. Slack-derived documents are internal-only; see kb_slack_routes for the purge on
app_uninstalled / tokens_revoked (Policy: delete within 14 business days).

Objects (under kb_store.PREFIX):
    slack/state.json              sync flags + per-channel watermarks + the team's domain
    slack/channels.json           {channel_id: {"client": key|"" , "name", "by", "at"}}  declared by a person
    slack/unassigned/<key>.json   a conversation waiting for a person, with the ladder's proposal
    slack/inbox/<event_id>.json   raw events, for the audit trail and idempotency
"""
import datetime as _dt
import hashlib
import hmac
import html
import json
import logging
import os
import re
import time
import zoneinfo

import requests

import kb_index
import kb_store
import kb_fathom

log = logging.getLogger("kb_slack")

API_BASE = "https://slack.com/api"
SIGNATURE_TOLERANCE_S = 300
PAGE_LIMIT = int(os.environ.get("SLACK_PAGE_LIMIT", "999"))     # the API maximum for history/replies
LOOKBACK_S = int(os.environ.get("SLACK_LOOKBACK_S", str(14 * 86400)))
# 🔴 WHY A LOOKBACK: `conversations.history` filters by the PARENT's timestamp, so a reply posted
# today to a thread started last week is invisible to "everything since the last sync". Re-reading
# two weeks of parents each sync and rebuilding only what changed (reindex_document is idempotent)
# is how late replies are caught without the Events API.
# 🔴 READ AT CALL TIME, NOT IMPORT TIME. The zone decides which DAY a message is filed under, so
# it has to be settable without a redeploy - and a module-level constant is frozen by whoever
# imports kb_slack first, which silently defeated four tests until 2026-09-18 (they passed only
# when their module happened to be imported first). Use tz_name()/_tz(), never a cached value.
# Asia/Manila, not the clients' Australia/Sydney: the day boundary should fall where the people
# TYPING the messages are, so an evening conversation stays on the evening it happened. Chosen by
# Jerome 2026-09-18, after the first real sync rendered Christian's 11:38 message as 13:38.
TZ_DEFAULT = "Asia/Manila"


def tz_name():
    """The zone whose calendar day a message is filed under (env SLACK_TZ)."""
    return (os.environ.get("SLACK_TZ") or TZ_DEFAULT).strip() or TZ_DEFAULT

MAX_RETRY_WAIT_S = 60
# 🔴 PRIVATE CHANNELS ARE NOT READ UNTIL SOMEONE SAYS SO. The manifest asks for public scopes only,
# but a scope added later would make conversations.list return private channels too, and the
# library has no per-reader membership filter yet (workbook S5-01) - a private channel filed today
# is readable by every staff member tomorrow. So private channels are listed (the page shows them)
# and SKIPPED by the sync until SLACK_ALLOW_PRIVATE=1, which is the moment the filter has to exist.
ALLOW_PRIVATE = os.environ.get("SLACK_ALLOW_PRIVATE", "").strip().lower() in ("1", "true", "on", "yes")
SYNC_STALE_S = kb_fathom.SYNC_STALE_S

AGENCY = ""
SOURCE = "slack"
KIND = "conversation"
FOLDER_ROOT = "Slack"
_STATE = "slack/state.json"
_CHANNELS = "slack/channels.json"
_UNASSIGNED = "slack/unassigned"
_INBOX = "slack/inbox"

# Providers that may NOT be shown Slack-derived text. Moonshot's Kimi terms (read 2026-09-17,
# last updated 2026-07-30) let it use API content "to improve Moonshot AI models" unless a separate
# written agreement says otherwise; Slack's Developer Policy forbids using its Data to train an LLM
# under any circumstances. So the two never meet. Gemini (paid tier), Vertex and Anthropic say no
# training on inputs. Env so a signed no-training agreement is a config change, not a deploy.
EXCLUDE_PROVIDERS = frozenset(p.strip().lower() for p in os.environ.get("KB_SLACK_EXCLUDE_PROVIDERS", "kimi").split(",")
                              if p.strip())


def withhold_from(excerpts, metas):
    """The providers that may not see THIS prompt: EXCLUDE_PROVIDERS when any retrieved passage
    comes from a Slack document, () otherwise. `metas` = kb_index.all_meta()."""
    for ex in excerpts or []:
        m = (metas or {}).get(ex.get("document_id")) or {}
        if m.get("source") == SOURCE or m.get("kind") == KIND:
            return tuple(sorted(EXCLUDE_PROVIDERS))
    return ()


# Message subtypes that are furniture, not conversation. Everything else is kept.
SKIP_SUBTYPES = frozenset(("channel_join", "channel_leave", "channel_topic", "channel_purpose", "channel_name",
                           "channel_archive", "channel_unarchive", "group_join", "group_leave", "pinned_item",
                           "unpinned_item", "bot_add", "bot_remove", "reminder_add", "tombstone"))


def enabled():
    return bool(os.environ.get("SLACK_BOT_TOKEN"))


def token():
    return os.environ.get("SLACK_BOT_TOKEN", "")


def signing_secret():
    return os.environ.get("SLACK_SIGNING_SECRET", "")


# --- inbound signing -----------------------------------------------------------------------------

def verify_signature(headers, body, secret, now=None):
    """True iff X-Slack-Signature == 'v0=' + HMAC-SHA256(secret, 'v0:<ts>:<raw body>') and the
    timestamp is within tolerance. Constant-time compare. `body` = the RAW request bytes."""
    if not secret:
        return False
    h = {k.lower(): v for k, v in (headers or {}).items()}
    ts, sig = h.get("x-slack-request-timestamp"), h.get("x-slack-signature")
    if not (ts and sig):
        return False
    try:
        if abs((now or time.time()) - int(ts)) > SIGNATURE_TOLERANCE_S:
            return False
    except ValueError:
        return False
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8")
    signed = f"v0:{ts}:".encode("utf-8") + raw
    expected = "v0=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig.strip(), expected)


# --- the Web API ---------------------------------------------------------------------------------

class SlackError(RuntimeError):
    pass


def call(method, params=None, tok=None, _get=None, _sleep=time.sleep):
    """GET one Web API method. Slack answers 200 with {"ok": false, "error": ...} for most failures,
    so the body is the thing to check, not the status. A 429 is honoured via Retry-After (bounded)."""
    tok = tok or token()
    get = _get or (lambda url, p: requests.get(url, params=p, headers={"Authorization": f"Bearer {tok}"}, timeout=60))
    for attempt in range(4):
        r = get(f"{API_BASE}/{method}", params or {})
        if r.status_code == 429:
            wait = min(int(r.headers.get("Retry-After", "5") or 5), MAX_RETRY_WAIT_S)
            log.warning("slack %s: rate limited, waiting %ss", method, wait)
            _sleep(wait)
            continue
        if r.status_code != 200:
            raise SlackError(f"{method}: HTTP {r.status_code}: {r.text[:200]}")
        j = r.json() or {}
        if not j.get("ok"):
            raise SlackError(f"{method}: {j.get('error') or 'not ok'}")
        return j
    raise SlackError(f"{method}: still rate limited after 4 attempts")


def paged(method, params, key, tok=None, _get=None):
    """Follow `response_metadata.next_cursor`; yield each item of `key`. Also yields nothing
    special for is_limited - the caller reads it off the first page via `paged_meta`."""
    cursor = None
    p = dict(params)
    while True:
        if cursor:
            p["cursor"] = cursor
        j = call(method, p, tok=tok, _get=_get)
        for item in j.get(key) or []:
            yield item
        cursor = ((j.get("response_metadata") or {}).get("next_cursor") or "").strip()
        if not cursor:
            break


def auth_test(tok=None, _get=None):
    """-> {"team", "team_id", "user_id", "url"} for the status panel."""
    j = call("auth.test", tok=tok, _get=_get)
    return {"team": j.get("team", ""), "team_id": j.get("team_id", ""), "user_id": j.get("user_id", ""),
            "url": j.get("url", "")}


def readable(channel):
    """May the sync READ this channel? Public: yes. Private: only with SLACK_ALLOW_PRIVATE."""
    return not channel.get("is_private") or ALLOW_PRIVATE


def list_channels(tok=None, _get=None, types="public_channel,private_channel"):
    """Channels the bot is a MEMBER of - the only ones it can read, so the only ones that exist as
    far as the library is concerned. Private channels appear only if the app has groups:* scopes."""
    out = []
    try:
        items = list(paged("conversations.list", {"types": types, "exclude_archived": "true", "limit": 999},
                           "channels", tok=tok, _get=_get))
    except SlackError as e:
        if "missing_scope" in str(e) and "private" in types:     # public-only app: ask again for what it may see
            return list_channels(tok=tok, _get=_get, types="public_channel")
        raise
    for c in items:
        if not c.get("is_member"):
            continue
        out.append({"id": c.get("id"), "name": c.get("name", ""), "is_private": bool(c.get("is_private")),
                    "members": int(c.get("num_members") or 0), "topic": ((c.get("topic") or {}).get("value") or "")[:200],
                    "purpose": ((c.get("purpose") or {}).get("value") or "")[:200]})
    return sorted(out, key=lambda c: c["name"])


_USERS = {"at": 0.0, "by_id": {}}
_USERS_TTL = 6 * 3600


def users(tok=None, _get=None, force=False):
    """{user_id: {"name", "email", "is_bot"}} - the whole directory, cached 6h. Mentions and
    speaker lines read names from here; nothing else is kept about a person."""
    if not force and _USERS["by_id"] and time.time() - _USERS["at"] < _USERS_TTL:
        return _USERS["by_id"]
    by_id = {}
    for u in paged("users.list", {"limit": 999}, "members", tok=tok, _get=_get):
        prof = u.get("profile") or {}
        by_id[u.get("id")] = {"name": (prof.get("display_name") or prof.get("real_name") or u.get("real_name")
                                       or u.get("name") or u.get("id") or "").strip(),
                              "email": (prof.get("email") or "").strip().lower(), "is_bot": bool(u.get("is_bot"))}
    _USERS.update(at=time.time(), by_id=by_id)
    return by_id


def fetch_history(channel_id, oldest=None, latest=None, tok=None, _get=None):
    """Top-level messages of a channel, oldest first, with each thread's replies attached as
    `_replies` (via conversations.replies). -> (messages, is_limited). `is_limited` is what a free
    plan says when history older than its window was withheld - recorded, never swallowed."""
    p = {"channel": channel_id, "limit": PAGE_LIMIT, "inclusive": "true"}
    if oldest:
        p["oldest"] = str(oldest)
    if latest:
        p["latest"] = str(latest)
    first = call("conversations.history", p, tok=tok, _get=_get)
    is_limited = bool(first.get("is_limited"))
    msgs = list(first.get("messages") or [])
    cursor = ((first.get("response_metadata") or {}).get("next_cursor") or "").strip()
    while cursor:
        j = call("conversations.history", dict(p, cursor=cursor), tok=tok, _get=_get)
        msgs += j.get("messages") or []
        cursor = ((j.get("response_metadata") or {}).get("next_cursor") or "").strip()
    for m in msgs:
        if int(m.get("reply_count") or 0) > 0 and m.get("ts"):
            reps = list(paged("conversations.replies", {"channel": channel_id, "ts": m["ts"], "limit": PAGE_LIMIT},
                              "messages", tok=tok, _get=_get))
            m["_replies"] = [r for r in reps if r.get("ts") != m.get("ts")]
    msgs.sort(key=lambda m: float(m.get("ts") or 0))
    return msgs, is_limited


# --- text ----------------------------------------------------------------------------------------

_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|([^>]*))?>")
_CHANNEL = re.compile(r"<#(C[A-Z0-9]+)(?:\|([^>]*))?>")
_SPECIAL = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")
_SUBTEAM = re.compile(r"<!subteam\^[A-Z0-9]+(?:\|@?([^>]*))?>")
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")


def render_text(text, users_by_id=None, channels_by_id=None):
    """Slack mrkdwn -> plain readable text: <@U..> to a name, <#C..> to #name, <url|label> to
    'label (url)', &amp; unescaped. Formatting marks (*_~`) are left alone - they read fine."""
    u, c = users_by_id or {}, channels_by_id or {}
    t = str(text or "")
    t = _MENTION.sub(lambda m: "@" + ((m.group(2) or (u.get(m.group(1)) or {}).get("name") or m.group(1))), t)
    t = _CHANNEL.sub(lambda m: "#" + (m.group(2) or (c.get(m.group(1)) or {}).get("name") or m.group(1)), t)
    t = _SPECIAL.sub(lambda m: "@" + m.group(1), t)
    t = _SUBTEAM.sub(lambda m: "@" + (m.group(1) or "team"), t)
    t = _LINK.sub(lambda m: f"{m.group(2)} ({m.group(1)})" if m.group(2) and m.group(2) != m.group(1) else m.group(1), t)
    return html.unescape(t).strip()


def _tz():
    try:
        return zoneinfo.ZoneInfo(tz_name())
    except Exception:                        # noqa: BLE001 - a bad TZ name must not stop filing
        log.warning("slack: unknown SLACK_TZ %r - filing days in UTC", tz_name())
        return _dt.timezone.utc


def when(ts):
    """Slack ts ('1726543210.123456') -> aware datetime in the library's day zone."""
    return _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).astimezone(_tz())


def speaker(m, users_by_id):
    if m.get("user"):
        return (users_by_id.get(m["user"]) or {}).get("name") or m["user"]
    return (m.get("username") or (m.get("bot_profile") or {}).get("name") or "bot").strip()


def message_line(m, users_by_id, channels_by_id=None):
    """'[HH:MM] Name: text' plus '[file: name]' for each attachment (names only - no download)."""
    text = render_text(m.get("text"), users_by_id, channels_by_id)
    files = [f"[file: {(f.get('title') or f.get('name') or 'file')}]" for f in (m.get("files") or [])]
    if not text and (m.get("attachments") or []):
        text = " ".join(render_text(a.get("fallback") or a.get("title") or "", users_by_id) for a in m["attachments"]).strip()
    body = " ".join(filter(None, [text] + files)) or "(no text)"
    return f"[{when(m['ts']).strftime('%H:%M')}] {speaker(m, users_by_id)}: {body}"


def keep(m):
    return bool(m.get("ts")) and (m.get("subtype") or "") not in SKIP_SUBTYPES


# --- conversations -------------------------------------------------------------------------------

def group_conversations(messages, channel):
    """Top-level messages -> conversations. A message with replies is a THREAD (parent + replies);
    unthreaded messages of one calendar day are a DAY conversation. -> [conv], each
    {"key", "kind": "thread"|"day", "channel", "messages": [..], "started": iso, "day": "YYYY-MM-DD",
     "thread_ts"}. `channel` = {"id", "name", "is_private"}."""
    threads, days = [], {}
    for m in messages:
        if not keep(m):
            continue
        if m.get("_replies"):
            reps = [r for r in m["_replies"] if keep(r)]
            threads.append({"key": f"t{m['ts'].replace('.', '-')}", "kind": "thread", "channel": channel,
                            "messages": [m] + sorted(reps, key=lambda r: float(r["ts"])),
                            "started": when(m["ts"]).isoformat(), "day": when(m["ts"]).strftime("%Y-%m-%d"),
                            "thread_ts": m["ts"]})
        else:
            d = when(m["ts"]).strftime("%Y-%m-%d")
            days.setdefault(d, []).append(m)
    out = threads
    for d, ms in days.items():
        ms.sort(key=lambda r: float(r["ts"]))
        out.append({"key": f"d{d}", "kind": "day", "channel": channel, "messages": ms,
                    "started": when(ms[0]["ts"]).isoformat(), "day": d, "thread_ts": ""})
    out.sort(key=lambda c: c["started"])
    return out


def doc_id(channel_id, key):
    cid = re.sub(r"[^A-Za-z0-9_-]", "-", str(channel_id))[:20]
    k = re.sub(r"[^A-Za-z0-9_-]", "-", str(key))[:30]
    return f"slack-{cid}-{k}"


def permalink(team_url, channel_id, ts):
    base = (team_url or "https://slack.com/").rstrip("/")
    return f"{base}/archives/{channel_id}/p{str(ts).replace('.', '')}" if ts else f"{base}/archives/{channel_id}"


def conversation_title(conv, users_by_id):
    ch = conv["channel"]["name"]
    if conv["kind"] == "thread":
        first = render_text(conv["messages"][0].get("text"), users_by_id).split("\n", 1)[0].strip()
        first = re.sub(r"\s+", " ", first)[:90] or "thread"
        return f"{first} (#{ch}, {conv['day']})"
    return f"#{ch} - {conv['day']}"


def conversation_body(conv, users_by_id, channels_by_id=None, team_url=""):
    """One '[HH:MM] Name: text' line per message, under a header that says where it came from.
    A cut is DECLARED in the text (kb_extract's rule), never silent."""
    ch = conv["channel"]
    head = f"## #{ch['name']} - {conv['day']}" + (" (thread)" if conv["kind"] == "thread" else "")
    link = permalink(team_url, ch["id"], conv.get("thread_ts") or conv["messages"][0].get("ts"))
    lines = [message_line(m, users_by_id, channels_by_id) for m in conv["messages"]]
    # 🔴 ONE MESSAGE = ONE BLOCK. kb_chunk packs whole blank-line-separated blocks and only cuts a
    # block that is itself over the budget - so messages joined by single newlines would be ONE
    # block and get sliced mid-sentence into 220-word windows. A blank line between messages makes
    # every passage a set of whole messages (checked in test_kb_slack.Chunking).
    body, cut = "", False
    for ln in lines:
        if len(body) + len(ln) + 2 > kb_store.MAX_BODY_CHARS - 2000:
            cut = True
            break
        body += ln + "\n\n"
    parts = [head + f"\nOpen in Slack: {link}\n{len(conv['messages'])} message(s)", body.rstrip("\n")]
    if cut:
        parts.append("[Import note: this conversation was cut to fit. Anything past this point is unknown, not absent.]")
    return "\n\n".join(p for p in parts if p)


def authors(conv, users_by_id):
    """The people who SPOKE, in the invitee shape kb_memory reads: {email, email_domain, name}. A
    colleague is internal by domain (kb_memory.INTERNAL_DOMAINS) whatever Slack says, so only a
    guest - a Slack Connect client contact, say - is ever learned as belonging to a client. Bots and
    users without an email contribute nothing."""
    seen, out = set(), []
    for m in conv["messages"]:
        u = (users_by_id or {}).get(m.get("user") or "") or {}
        email = (u.get("email") or "").strip().lower()
        if not email or u.get("is_bot") or email in seen:
            continue
        seen.add(email)
        out.append({"email": email, "email_domain": email.rsplit("@", 1)[-1], "name": u.get("name") or ""})
    return out


def as_meeting(conv, users_by_id):
    """A meeting-shaped view for kb_fathom.classify and kb_memory: the ladder reads title, transcript
    turns and invitees. The "invitees" are the people who spoke (`authors`), so a recurring guest
    teaches memory and is matched by it exactly as on a call; an all-staff channel has no external
    author, rung 0/1 contribute nothing and the transcript decides - the rule Jerome set for meetings."""
    return {"recording_id": doc_id(conv["channel"]["id"], conv["key"]),
            "title": f"#{conv['channel']['name']} " + conversation_title(conv, users_by_id),
            "created_at": conv["started"],
            "calendar_invitees": authors(conv, users_by_id),
            "transcript": [{"speaker": {"display_name": speaker(m, users_by_id)},
                            "text": render_text(m.get("text"), users_by_id),
                            "timestamp": when(m["ts"]).strftime("%H:%M:%S")} for m in conv["messages"]]}


# --- state, mapping, queue -----------------------------------------------------------------------

def state():
    return kb_store._read_json(_STATE, default={}) or {}


def save_state(st):
    kb_store._write_json(_STATE, st)


def syncing(st=None):
    return kb_fathom.syncing(state() if st is None else st)


def channel_map():
    """{channel_id: {"client": key|"", "name", "by", "at"}} - DECLARED by a person on the page."""
    return kb_store._read_json(_CHANNELS, default={}) or {}


def set_channel_client(channel_id, client_key, name="", by=""):
    """Map a channel to a client ('' = agency-wide) or clear it (None). -> the saved map."""
    cm = channel_map()
    if client_key is None:
        cm.pop(channel_id, None)
    else:
        cm[channel_id] = {"client": kb_store.client_key(client_key), "name": name or (cm.get(channel_id) or {}).get("name", ""),
                          "by": by, "at": kb_store.now()}
    kb_store._write_json(_CHANNELS, cm)
    return cm


def channel_client(channel_id, cm=None):
    """The declared client for a channel, or None when nobody has said."""
    rec = (cm if cm is not None else channel_map()).get(channel_id)
    return None if rec is None else rec.get("client", "")


def _q(key):
    return f"{_UNASSIGNED}/{re.sub(r'[^A-Za-z0-9_-]', '-', key)}.json"


def _teaches(conv, users_by_id):
    """What a human Assign WOULD record - the external people who spoke. Shown on the card with tick
    boxes, the meetings pattern. Titles are not offered: a thread's first line is not recurring."""
    try:
        import kb_memory
        t = kb_memory.teaches(as_meeting(conv, users_by_id))
        return {"people": t.get("people", []), "domains": t.get("domains", []), "title": ""}
    except Exception:                        # noqa: BLE001
        return {"people": [], "domains": [], "title": ""}


def store_unassigned(conv, proposal=None, users_by_id=None):
    key = doc_id(conv["channel"]["id"], conv["key"])
    rec = {"key": key, "channel": conv["channel"], "kind": conv["kind"], "day": conv["day"],
           "title": conversation_title(conv, users_by_id or {}), "started": conv["started"],
           "messages": len(conv["messages"]),
           "preview": [message_line(m, users_by_id or {}) for m in conv["messages"][:6]],
           "will_learn": _teaches(conv, users_by_id or {}),
           "conversation": conv, "proposal": proposal, "queued_at": kb_store.now()}
    kb_store._write_json(_q(key), rec)
    return rec


def list_unassigned():
    out = []
    try:
        blobs = kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=f"{kb_store.PREFIX}/{_UNASSIGNED}/")
        for b in blobs:
            try:
                rec = json.loads(b.download_as_bytes().decode("utf-8"))
            except Exception:                # noqa: BLE001
                continue
            rec.pop("conversation", None)    # the card does not need every message
            out.append(rec)
    except Exception:                        # noqa: BLE001
        log.exception("slack: could not list the queue")
    return sorted(out, key=lambda r: r.get("started", ""), reverse=True)


def load_unassigned(key):
    return kb_store._read_json(_q(key), default=None)


def drop_unassigned(key):
    prefix = f"{kb_store.PREFIX}/{_q(key)}"
    try:
        for b in kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=prefix):
            b.delete()
    except Exception:                        # noqa: BLE001 - already gone is fine
        log.debug("slack: could not drop queue entry %s", key, exc_info=True)


# --- filing --------------------------------------------------------------------------------------

def already_indexed(did):
    doc = kb_store.read_doc(did)
    if not doc or doc.get("archived"):
        return None
    return doc.get("client") or AGENCY


def index_conversation(conv, client_key, assigned_by, evidence=None, actor="", users_by_id=None,
                       channels_by_id=None, team_url="", skip_learning=None):
    """File one conversation as a kb document under `client_key` ("" = agency-wide), keep the raw
    messages as its file, clear the queue entry, and - on a HUMAN assignment to a client - let the
    people who spoke teach memory (kb_memory.learn over `authors`; `skip_learning` = what the person
    unticked). A channel mapping and a model filing teach nothing: the first is already certain, the
    second must never teach the next guess (the meetings rule). Re-filing the same key REPLACES the
    document (same id), which is how an edit or a delete upstream reaches the library."""
    ck = kb_store.client_key(client_key)
    did = doc_id(conv["channel"]["id"], conv["key"])
    ch = conv["channel"]
    ub = users_by_id or {}
    body = conversation_body(conv, ub, channels_by_id, team_url)
    doc = kb_store.make_doc(title=conversation_title(conv, ub), body=body, kind=KIND,
                            folder=f"{FOLDER_ROOT}/#{ch['name']}", source=SOURCE, owner=actor or "slack",
                            filename="conversation.json", mime="application/json",
                            size_bytes=len(json.dumps(conv["messages"])), doc_id=did, client=ck)
    doc["slack"] = {"channel_id": ch["id"], "channel_name": ch["name"], "is_private": bool(ch.get("is_private")),
                    "kind": conv["kind"], "day": conv["day"], "thread_ts": conv.get("thread_ts", ""),
                    "started": conv["started"], "messages": len(conv["messages"]),
                    "permalink": permalink(team_url, ch["id"], conv.get("thread_ts") or conv["messages"][0].get("ts")),
                    "assigned_by": assigned_by, "assignment_evidence": list(evidence or [])[:20]}
    try:
        kb_store.write_file(did, "conversation.json", json.dumps(conv["messages"], ensure_ascii=False).encode("utf-8"),
                            content_type="application/json")
    except Exception:                        # noqa: BLE001 - the text is the searchable part
        log.exception("slack: could not keep the raw messages for %s", did)
    rep = kb_index.reindex_document(doc)
    if assigned_by == "human" and ck != AGENCY:
        try:
            import kb_memory
            kb_memory.learn(ck, as_meeting(conv, ub), did, skip=skip_learning)
        except Exception:                    # noqa: BLE001 - memory mirrors; the document is filed
            log.exception("slack: memory.learn failed for %s", did)
    drop_unassigned(did)
    meta = kb_store.doc_meta(doc)
    meta.update(chunks=rep.get("chunks", 0), semantic=rep.get("semantic", False), assigned_by=assigned_by, key=did)
    return meta


def purge_all():
    """Delete every Slack-derived object: documents (and their chunks + files, via kb_store),
    the queue, the inbox, the mapping and the state. The Developer Policy's 14-business-day rule,
    done at once. -> counts."""
    counts = {"docs": 0, "objects": 0}
    for did, m in kb_index.all_meta(include_archived=True).items():
        if m.get("source") == SOURCE or str(did).startswith("slack-"):
            try:
                kb_store.delete_doc(did)
                counts["docs"] += 1
            except Exception:                # noqa: BLE001
                log.exception("slack purge: doc %s", did)
    try:
        for b in kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=f"{kb_store.PREFIX}/slack/"):
            b.delete()
            counts["objects"] += 1
    except Exception:                        # noqa: BLE001
        log.exception("slack purge: objects")
    return counts
