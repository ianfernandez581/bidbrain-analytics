"""kb_memory.py - what the system has LEARNED about each client from confirmed meeting assignments.

The Memory leg beside the library (RAG). The library remembers WORDS; this remembers ROUTING: which
people, recurring meeting titles and email domains belong to which client, so the next Fathom meeting
with the same people on the invite is filed without a model call and without a click.

One small JSON per client, in the knowledge base's own prefix so it travels with it:

    <PREFIX>/fathom/memory/<client_key>.json
    {"people":   {"priya@cloudflare.com": {"n": 3, "last": "...", "evidence": ["fathom-123", ...]}},
     "titles":   {"cloudflare weekly": {...}},        # normalised recurring meeting titles
     "domains":  {"partner-agency.co": {...}},        # learned: external domains seen on confirmed calls
     "patterns": {"APAC Core DG": {...}},             # campaign-name tokens the evidence bundle matched
     "client_domains": ["cloudflare.com"],            # DECLARED by a person: the ladder's first rung
     "facts":    ["NFP, no revenue - outcomes are enquiries"],   # hand-written; read by the assistants
     "updated_at": "..."}

🔴 WRITTEN ONLY BY CONFIRMED ASSIGNMENTS. `learn()` runs on a human Assign and on a deterministic
rung (domain, memory) - never on a model proposal, so a wrong guess cannot teach the next one.
`match()` looks a new meeting up across EVERY client's memory:

    exactly ONE client owns every matched key  -> ("assign", client_key, evidence)   deterministic
    a key is owned by 2+ clients               -> ("hint", {client: [evidence]}, ...) the fact stopped
                                                  being decisive (Priya joined a MongoDB call too);
                                                  handed to the evidence bundle, never asserted
    nothing matched                            -> (None, None, [])

Memory is facts ABOUT the client, never transcript text. `client_safe()` is the only slice the
CUSTOMER assistant may read: facts. People and domains never leave the building.
"""
import re
import datetime as _dt

import kb_store

_DIR = "fathom/memory"
MAX_KEYS_PER_KIND = 500
CLIENT_SAFE_KEYS = ("facts",)
LEARNED_KINDS = ("people", "titles", "domains", "patterns")
ALL_KINDS = LEARNED_KINDS + ("facts", "client_domains")


def _path(client_key):
    return f"{_DIR}/{kb_store.client_key(client_key) or '_agency'}.json"


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def empty():
    return {"people": {}, "titles": {}, "domains": {}, "patterns": {}, "client_domains": [],
            "facts": [], "updated_at": None}


def load(client_key):
    doc = kb_store._read_json(_path(client_key), default=None)
    base = empty()
    if isinstance(doc, dict):
        for k in base:
            if k in doc:
                base[k] = doc[k]
    return base


def save(client_key, doc):
    doc["updated_at"] = _now()
    kb_store._write_json(_path(client_key), doc)
    return doc


def list_clients():
    """Every client key that has a memory file."""
    out = []
    prefix = f"{kb_store.PREFIX}/{_DIR}/"
    for blob in kb_store._storage().list_blobs(kb_store.bucket_name(), prefix=prefix):
        name = blob.name.rsplit("/", 1)[-1]
        if name.endswith(".json"):
            out.append(name[:-5])
    return out


def load_all():
    """{client_key: memory} for every client with a file. Never raises: routing must not depend on it."""
    try:
        return {ck: load(ck) for ck in list_clients()}
    except Exception:                        # noqa: BLE001
        return {}


# --- normalise -----------------------------------------------------------------------------------

def norm_title(title):
    """'Cloudflare weekly - 12 Sep' -> 'cloudflare weekly'. Dates, weekdays and trailing noise go;
    the recurring stem stays. '' when nothing is left."""
    t = (title or "").lower()
    t = re.sub(r"\b\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", " ", t)
    t = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2}\b", " ", t)
    t = re.sub(r"\b(mon|tues?|wed(nes)?|thu(rs)?|fri|sat(ur)?|sun)(day)?\b", " ", t)
    t = re.sub(r"\b(19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b|\bq[1-4]\b|\bw\/?c\b|\bwk\s*\d+\b", " ", t)
    t = re.sub(r"[^a-z0-9& ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _bump(section, key, evidence):
    if not key:
        return
    rec = section.get(key) or {"n": 0, "evidence": []}
    rec["n"] = int(rec.get("n", 0)) + 1
    rec["last"] = _now()
    if evidence and evidence not in rec["evidence"]:
        rec["evidence"] = (rec["evidence"] + [evidence])[-10:]
    section[key] = rec
    if len(section) > MAX_KEYS_PER_KIND:          # drop the least-seen key
        victim = min(section, key=lambda k: (section[k].get("n", 0), section[k].get("last", "")))
        del section[victim]


# --- learn / edit --------------------------------------------------------------------------------

def teaches(meeting):
    """What `learn` WOULD record for this meeting - shown on the queue card before the click so the
    person can untick anything that should not be remembered (a guest who was only there once, a
    one-off title). -> {"people": [emails], "domains": [domains], "title": normalised title or ""}."""
    people, domains = [], []
    for inv in meeting.get("calendar_invitees") or []:
        email = (inv.get("email") or "").strip().lower()
        if not email or not inv.get("is_external", True):
            continue
        dom = (inv.get("email_domain") or email.rsplit("@", 1)[-1]).lower()
        if email not in people:
            people.append(email)
        if dom not in domains:
            domains.append(dom)
    return {"people": people, "domains": domains,
            "title": norm_title(meeting.get("title") or meeting.get("meeting_title"))}


def learn(client_key, meeting, evidence, patterns=None, skip=None):
    """Record what a CONFIRMED assignment teaches: every external invitee -> people (and their
    domain -> domains), the normalised title -> titles, campaign tokens the evidence bundle matched
    -> patterns. `evidence` is the document id. `skip` = items (emails, domains, the normalised
    title) the person unticked on the card; they are not recorded. Returns the saved memory."""
    skip = {str(s).strip().lower() for s in (skip or []) if str(s).strip()}
    doc = load(client_key)
    for inv in meeting.get("calendar_invitees") or []:
        email = (inv.get("email") or "").strip().lower()
        if not email or not inv.get("is_external", True):
            continue
        dom = (inv.get("email_domain") or email.rsplit("@", 1)[-1]).lower()
        if email not in skip:
            _bump(doc["people"], email, evidence)
        if dom not in skip:
            _bump(doc["domains"], dom, evidence)
    title = norm_title(meeting.get("title") or meeting.get("meeting_title"))
    if title and title not in skip:
        _bump(doc["titles"], title, evidence)
    for p in patterns or []:
        _bump(doc["patterns"], str(p).strip(), evidence)
    return save(client_key, doc)


def forget(client_key, kind, key):
    """Remove one entry (the card's 'remove' on a wrong fact). True if it existed."""
    if kind not in ALL_KINDS:
        return False
    doc = load(client_key)
    if kind in ("facts", "client_domains"):
        before = len(doc[kind])
        doc[kind] = [f for f in doc[kind] if f != key]
        changed = len(doc[kind]) != before
    else:
        changed = key in doc.get(kind, {})
        doc.get(kind, {}).pop(key, None)
    if changed:
        save(client_key, doc)
    return changed


def add_fact(client_key, text):
    text = (text or "").strip()[:400]
    if not text:
        return None
    doc = load(client_key)
    if text not in doc["facts"]:
        doc["facts"].append(text)
        save(client_key, doc)
    return doc


_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")


def set_client_domains(client_key, domains):
    """The DECLARED email domains for a client (rung 1). Lower-cased, de-duped, validated.
    -> (saved_list, bad_entries)."""
    clean, bad = [], []
    for d in domains or []:
        d = str(d).strip().lower().lstrip("@")
        if not d:
            continue
        (clean if _DOMAIN_RE.match(d) else bad).append(d)
    if bad:
        return None, bad
    doc = load(client_key)
    doc["client_domains"] = sorted(set(clean))
    save(client_key, doc)
    return doc["client_domains"], []


def all_client_domains(memories=None):
    """{client_key: [declared domains]} - what rung_domain reads."""
    mems = memories if memories is not None else load_all()
    return {ck: list(m.get("client_domains") or []) for ck, m in mems.items() if m.get("client_domains")}


# --- match ---------------------------------------------------------------------------------------

def match(meeting, memories):
    """Look a meeting up across every client's LEARNED memory. `memories` = {client_key: doc}.
    -> ("assign", client_key, [evidence]) | ("hint", {client_key: [evidence]}, [lines]) | (None, None, [])."""
    title = norm_title(meeting.get("title") or meeting.get("meeting_title"))
    emails = {(i.get("email") or "").strip().lower() for i in (meeting.get("calendar_invitees") or [])
              if i.get("email") and i.get("is_external", True)}
    hits = {}
    for ck, doc in (memories or {}).items():
        ev = []
        for e in emails:
            if e in (doc.get("people") or {}):
                ev.append(f"{e} seen on {doc['people'][e].get('n', 1)} confirmed meeting(s)")
        if title and title in (doc.get("titles") or {}):
            ev.append(f'recurring title "{title}" ({doc["titles"][title].get("n", 1)}x)')
        if ev:
            hits[ck] = ev
    if not hits:
        return None, None, []
    if len(hits) == 1:
        ck, ev = next(iter(hits.items()))
        return "assign", ck, ev
    return "hint", hits, [f"{ck}: {'; '.join(ev)}" for ck, ev in hits.items()]


def client_safe(doc):
    """The subset the CUSTOMER assistant may read: facts only, never people or domains."""
    return {k: doc.get(k) for k in CLIENT_SAFE_KEYS}


def profile_block(client_key, audience):
    """The CLIENT PROFILE lines for a prompt: facts (+ confirmed campaign-name patterns for staff);
    facts ONLY for the customer. '' when there is nothing or the store is unreachable."""
    try:
        mem = load(client_key)
    except Exception:                        # noqa: BLE001
        return ""
    if audience == "client":
        return "\n".join(f"- {f}" for f in (client_safe(mem).get("facts") or []))
    lines = [f"- {f}" for f in (mem.get("facts") or [])]
    pats = sorted((mem.get("patterns") or {}).items(), key=lambda kv: -int(kv[1].get("n", 0)))[:15]
    if pats:
        lines.append("- Campaign-name patterns confirmed for this client: " + ", ".join(p for p, _ in pats))
    return "\n".join(lines)
