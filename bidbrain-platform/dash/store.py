"""Persistence + password resolution for the platform front-door.

Backend = a single PRIVATE JSON object in GCS (the exact pattern every dashboard already uses —
no new GCP product, no database). The whole registry lives in one blob:

    gs://$GCS_BUCKET/$DATA_OBJECT  (default platform.json)
    {
      "admin_password_hash": "...",
      "agencies": [ {name, slug, password_hash, client_keys[], order} ],
      "clients":  { "<key>": {key,name,slug,status,url,password_hash,campaigns[],order} }
    }

Every operation is load-mutate-save on that one blob (read-modify-write, last-write-wins — fine for
a single-admin, low-traffic registry; the concurrency caveat is documented in the README). The
service reads it fresh per request and uploads with Cache-Control: no-store, so an admin edit is
visible immediately and across Cloud Run instances.

Set env `PLATFORM_BACKEND=memory` to run without GCS (local dev): the registry then lives
in-process, seeded from config.py, and edits are lost on restart.

Passwords are never stored in clear: pbkdf2_hmac (stdlib) with a random salt. `resolve_password`
is the login brain — it maps a typed password to admin / a specific agency / a single client.
"""
import os
import json
import hmac
import hashlib
import secrets as _secrets

import config as seed

_BACKEND = os.environ.get("PLATFORM_BACKEND", "gcs").lower()

# Every dashboard key the admin UI may attach (the 10 live services + the not-yet-built ones).
ALL_DASHBOARD_KEYS = sorted(set(list(seed.CLIENTS.keys()) + seed.UNASSIGNED_CLIENTS))


def _domain_of(email: str) -> str:
    """The domain part of an email, lowercased ('' if malformed). Exact match only — 'x@100.digital'
    -> '100.digital', but 'x@evil.100.digital' -> 'evil.100.digital' (a subdomain is NOT the domain)."""
    email = (email or "").strip().lower()
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def _admin_domains():
    """Domains whose verified Google accounts are admins by default (config.ADMIN_EMAIL_DOMAINS)."""
    return set(getattr(seed, "ADMIN_EMAIL_DOMAINS", []))


def _seed_users():
    """The config.py USERS seed as an {email: {role, agency_slug, client_key}} map (lowercased).

    These are the baked-in Google-account grants (e.g. the permanent super admin). `resolve_email`
    falls back to this map when an email isn't in the live registry, so a seed account always works
    even on a registry created before this feature — the same fail-safe idea as the SUPER_ADMIN_PW
    env fallback on the password path."""
    out = {}
    for u in getattr(seed, "USERS", []):
        em = (u.get("email") or "").strip().lower()
        if em:
            out[em] = {"role": u.get("role", "client"),
                       "agency_slug": u.get("agency_slug", ""),
                       "client_key": u.get("client_key", "")}
    return out


# --- password hashing (stdlib only) -------------------------------------------------------
def hash_pw(password: str) -> str:
    if not password:
        return ""
    salt = _secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"pbkdf2_sha256$120000${salt.hex()}${dk.hex()}"


def verify_pw(password: str, stored: str) -> bool:
    if not password or not stored or not stored.startswith("pbkdf2_sha256$"):
        return False
    try:
        _algo, iters, salt_hex, hash_hex = stored.split("$")
        iters = int(iters)
        if not (1_000 <= iters <= 1_000_000):  # clamp: a pathological stored count can't burn CPU on /login
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), iters)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _seed_doc():
    """The full registry dict built from config.py (seed for a fresh store / the memory backend).

    Passwords are stored as a one-way hash AND a recoverable `*_plain` copy. The plain copy is what
    lets the SUPER ADMIN console reveal a password (a hash can't be un-hashed); it lives only in the
    PRIVATE registry JSON — the same private-bucket trust boundary that already holds every
    dashboard's plaintext `<c>-dash-password` secret."""
    doc = {
        "admin_password_hash": hash_pw(seed.ADMIN_PW), "admin_password_plain": seed.ADMIN_PW,
        "super_admin_password_hash": hash_pw(seed.SUPER_ADMIN_PW),
        "super_admin_password_plain": seed.SUPER_ADMIN_PW,
        "agencies": [], "clients": {},
    }
    for i, a in enumerate(seed.AGENCIES):
        doc["agencies"].append({
            "name": a["name"], "slug": a["slug"],
            "password_hash": hash_pw(a["password"]), "password_plain": a.get("password", ""),
            "client_keys": list(a["clients"]), "order": i,
        })
    for i, (k, c) in enumerate(seed.CLIENTS.items()):
        pw = seed.CLIENT_PASSWORDS.get(k, "")
        doc["clients"][k] = {
            "key": k, "name": c["name"], "slug": c["slug"], "status": c["status"],
            "url": c.get("url", ""), "note": c.get("note", ""),
            "password_hash": hash_pw(pw), "password_plain": pw,
            "campaigns": [dict(cm) for cm in c.get("campaigns", [])], "order": i,
        }
    for k in seed.UNASSIGNED_CLIENTS:
        doc["clients"].setdefault(k, {
            "key": k, "name": k.upper(), "slug": k, "status": "active",
            "url": seed._runapp(k), "password_hash": "", "password_plain": "",
            "campaigns": [], "order": 99,
        })
    doc["users"] = _seed_users()
    return doc


# =========================================================================================
class Store:
    def __init__(self):
        if _BACKEND == "memory":
            self._mem = _seed_doc()
            self._bucket = None
        else:
            from google.cloud import storage  # lazy: keep off the import path in memory mode
            self._mem = None
            self._storage = storage.Client()
            self._bucket = self._storage.bucket(os.environ["GCS_BUCKET"])
            self._object = os.environ.get("DATA_OBJECT", "platform.json")

    # ---- the one blob: load / save ----
    @staticmethod
    def _empty():
        return {"admin_password_hash": "", "admin_password_plain": "",
                "super_admin_password_hash": "", "super_admin_password_plain": "",
                "agencies": [], "clients": {}, "users": {}}

    def _load(self):
        if self._mem is not None:
            return self._mem
        blob = self._bucket.blob(self._object)
        if not blob.exists():
            return self._empty()        # genuinely fresh registry — only this case is "empty"
        # A blob that EXISTS but won't download/parse must NOT degrade to _empty(): every mutator does
        # load -> mutate -> save (backfill_plaintext even runs on each super-admin render), so returning
        # empty here would let the next write persist a blank doc over a good registry — a full wipe.
        # Fail CLOSED: let the exception propagate so the caller aborts the read-modify-write.
        doc = json.loads(blob.download_as_bytes())
        doc.setdefault("agencies", [])
        doc.setdefault("clients", {})
        doc.setdefault("admin_password_hash", "")
        doc.setdefault("admin_password_plain", "")
        doc.setdefault("super_admin_password_hash", "")
        doc.setdefault("super_admin_password_plain", "")
        doc.setdefault("users", {})
        return doc

    def _save(self, doc):
        if self._mem is not None:
            self._mem = doc
            return
        blob = self._bucket.blob(self._object)
        blob.cache_control = "no-store"
        blob.upload_from_string(json.dumps(doc, separators=(",", ":")),
                                content_type="application/json")

    def seed(self, force=False):
        """Write the config.py seed to the store. Refuses if already populated unless force.
        On force, a client's dashboard password_hash is PRESERVED unless config supplies one
        (so a re-seed never blanks a password rotated directly in the store)."""
        existing = self._load()
        if not force and (existing.get("agencies") or existing.get("clients")):
            return False
        doc = _seed_doc()
        if force:
            for k, c in doc["clients"].items():
                if not seed.CLIENT_PASSWORDS.get(k, ""):
                    prior = existing.get("clients", {}).get(k, {})
                    c["password_hash"] = prior.get("password_hash", c["password_hash"])
                    c["password_plain"] = prior.get("password_plain", c["password_plain"])
            # keep Google-account grants added live in the console (config seeds re-apply on top)
            for em, rec in existing.get("users", {}).items():
                doc.setdefault("users", {}).setdefault(em, rec)
        self._save(doc)
        return True

    # ---- reads ----
    def _all_agencies(self):
        return sorted(self._load().get("agencies", []), key=lambda a: a.get("order", 0))

    def _all_clients(self):
        return dict(self._load().get("clients", {}))

    def _client(self, key):
        return self._load().get("clients", {}).get(key)

    def get_client(self, key):
        return self._load().get("clients", {}).get(key)

    def get_agency(self, slug):
        if not slug:
            return None
        for a in self._load().get("agencies", []):
            if a.get("slug") == slug:
                return a
        return None

    def _admin_hash(self):
        return self._load().get("admin_password_hash", "")

    def get_state(self):
        """The shape the templates consume: agencies(with nested clients+campaigns) + unassigned."""
        clients = self._all_clients()
        agencies, assigned = [], set()
        for a in self._all_agencies():
            kids = []
            for key in a.get("client_keys", []):
                c = clients.get(key)
                if not c:
                    continue
                assigned.add(key)
                kids.append({
                    "key": key, "name": c["name"], "slug": c["slug"], "status": c["status"],
                    "url": c.get("url", ""), "campaigns": c.get("campaigns", []),
                    "note": c.get("note", ""),
                })
            # active (client-facing live) tiles first; coming_soon (no live dashboard) drop to the bottom
            kids.sort(key=lambda c: 0 if c.get("status") == "active" else 1)
            agencies.append({"name": a["name"], "slug": a["slug"], "clients": kids})
        unassigned = [
            {"key": k, "name": c["name"], "slug": c["slug"],
             "note": "on hold" if k == "stt" else "no agency"}
            for k, c in clients.items() if k not in assigned
        ]
        return {"agencies": agencies, "unassigned": unassigned, "all_client_keys": ALL_DASHBOARD_KEYS}

    # ---- login resolution ----
    def resolve_password(self, password):
        """('superadmin', None) | ('admin', None) | ('agency', a) | ('client', c) | (None, None).

        Super admin is checked FIRST. It resolves against the registry hash if one is set; if the
        registry has no super-admin hash yet (a not-yet-configured live registry), it falls back to
        the bootstrap `SUPER_ADMIN_PW` env (config.SUPER_ADMIN_PW), so the god-mode login works the
        moment the env is injected, before anyone re-seeds. Once a super admin sets a password in the
        UI the registry hash exists and the env fallback is ignored."""
        if not password:
            return None, None
        doc = self._load()
        super_hash = doc.get("super_admin_password_hash", "")
        if super_hash:
            if verify_pw(password, super_hash):
                return "superadmin", None
        elif getattr(seed, "SUPER_ADMIN_PW", "") and \
                hmac.compare_digest(password.encode(), seed.SUPER_ADMIN_PW.encode()):
            return "superadmin", None
        if verify_pw(password, doc.get("admin_password_hash", "")):
            return "admin", None
        for a in sorted(doc.get("agencies", []), key=lambda a: a.get("order", 0)):
            if verify_pw(password, a.get("password_hash", "")):
                return "agency", a
        for key, c in doc.get("clients", {}).items():
            if verify_pw(password, c.get("password_hash", "")):
                return "client", c
        return None, None

    # ---- login resolution: a VERIFIED Google email -> the same (kind, payload) shape ----
    def resolve_email(self, email):
        """Map a verified Google email to ('superadmin'|'admin'|'agency'|'client', payload)|(None,None).

        Mirrors resolve_password but keyed on the registry `users` map (managed in the super-admin
        console), with a config.USERS fallback so a baked-in account (the permanent super admin)
        always resolves even on a registry seeded before Google login existed. agency/client grants
        return the SAME agency/client dicts resolve_password yields, so login handling is identical."""
        if not email:
            return None, None
        email = email.strip().lower()
        doc = self._load()
        rec = doc.get("users", {}).get(email) or _seed_users().get(email)
        if not rec:
            # Domain fallback: a verified account on an admin domain (e.g. @100.digital) is an admin by
            # default, even before its email is recorded — so the very FIRST Google login succeeds. An
            # explicit record above always wins, so a domain user re-scoped/removed in the console keeps
            # that assignment (record_domain_admin persists the grant on first login for exactly this).
            if _domain_of(email) in _admin_domains():
                return "admin", None
            return None, None
        role = rec.get("role")
        if role == "superadmin":
            return "superadmin", None
        if role == "admin":
            return "admin", None
        if role == "agency":
            a = next((x for x in doc.get("agencies", []) if x.get("slug") == rec.get("agency_slug")), None)
            return ("agency", a) if a else (None, None)
        if role == "client":
            c = doc.get("clients", {}).get(rec.get("client_key"))
            return ("client", c) if c else (None, None)
        return None, None

    def record_domain_admin(self, email):
        """Persist a domain-granted admin (see config.ADMIN_EMAIL_DOMAINS) into the registry `users`
        map so it shows up — and becomes editable/removable — in the super-admin console's "Google
        sign-in access" panel. Returns True iff a NEW row was written. Idempotent and no-op unless the
        email is on an admin domain AND has no explicit record yet: so a seed account (the permanent
        super admin) or an account already re-scoped in the console is never overwritten to admin."""
        email = (email or "").strip().lower()
        if _domain_of(email) not in _admin_domains():
            return False
        doc = self._load()
        if email in doc.get("users", {}) or email in _seed_users():
            return False
        doc.setdefault("users", {})[email] = {"role": "admin", "agency_slug": "", "client_key": ""}
        self._save(doc)
        return True

    def upsert_user(self, email, role, agency_slug="", client_key=""):
        doc = self._load()
        doc.setdefault("users", {})[email.strip().lower()] = {
            "role": role, "agency_slug": agency_slug, "client_key": client_key}
        self._save(doc)

    def delete_user(self, email):
        doc = self._load()
        if doc.setdefault("users", {}).pop(email.strip().lower(), None) is not None:
            self._save(doc)

    def list_users(self):
        """Registry users merged with the config seeds (a registry row overrides a seed of the same
        email). Each row is flagged `seed` — a baked-in grant `resolve_email` falls back to, so
        deleting it in the UI can't actually revoke it; the UI marks it non-removable."""
        reg = dict(self._load().get("users", {}))
        seeds = _seed_users()
        merged = {**seeds, **reg}
        rank = {"superadmin": 0, "admin": 1, "agency": 2, "client": 3}
        out = [{"email": em, "role": r.get("role", "client"),
                "agency_slug": r.get("agency_slug", ""), "client_key": r.get("client_key", ""),
                "seed": em in seeds} for em, r in merged.items()]
        return sorted(out, key=lambda u: (rank.get(u["role"], 9), u["email"]))

    def agency_clients(self, agency):
        """Resolved client dicts (for the portal), in the agency's order."""
        clients = self._all_clients()
        out = []
        for key in agency.get("client_keys", []):
            c = clients.get(key)
            if c:
                out.append({"key": key, "name": c["name"], "slug": c["slug"],
                            "status": c["status"], "url": c.get("url", ""),
                            "campaigns": c.get("campaigns", [])})
        return out

    def active_client_keys(self):
        """Every live (status=='active') client key — across agencies AND unassigned. The admin
        SSO grant uses this so it covers live-but-unassigned dashboards (hireright) and excludes
        coming_soon ones (bellshakespeare/geocon)."""
        return [k for k, c in self._all_clients().items() if c.get("status") == "active"]

    # ---- writes (admin CRUD): load → mutate → save the one blob ----
    @staticmethod
    def _next_order(items):
        return max([i.get("order", 0) for i in items], default=-1) + 1

    def upsert_agency(self, orig_slug, name, slug, password):
        doc = self._load()
        agencies = doc.setdefault("agencies", [])
        existing = next((a for a in agencies if a["slug"] == orig_slug), None) if orig_slug else None
        new_agency = {
            "name": name, "slug": slug,
            "password_hash": hash_pw(password) if password else (existing or {}).get("password_hash", ""),
            # keep a recoverable copy in lock-step with the hash, so the super-admin console can reveal it
            "password_plain": password if password else (existing or {}).get("password_plain", ""),
            "client_keys": (existing or {}).get("client_keys", []),
            "order": (existing or {}).get("order", self._next_order(agencies)),
        }
        agencies = [a for a in agencies if a["slug"] not in ({orig_slug, slug} if orig_slug else {slug})]
        agencies.append(new_agency)
        doc["agencies"] = agencies
        self._save(doc)

    def delete_agency(self, slug):
        doc = self._load()
        doc["agencies"] = [a for a in doc.get("agencies", []) if a["slug"] != slug]
        self._save(doc)  # clients persist; they fall into "unassigned"

    def upsert_client(self, agency_slug, key, name, slug, status, url, note=None):
        doc = self._load()
        # Validate the target agency BEFORE writing, so a stale/deleted agency_slug can't orphan it.
        if agency_slug and not any(a["slug"] == agency_slug for a in doc.get("agencies", [])):
            raise ValueError(f"unknown agency '{agency_slug}'")
        clients = doc.setdefault("clients", {})
        existing = clients.get(key, {})
        clients[key] = {
            "key": key, "name": name, "slug": slug, "status": status, "url": url,
            # optional placeholder blurb shown on coming_soon tiles + the super console (note=None preserves)
            "note": existing.get("note", "") if note is None else note,
            "password_hash": existing.get("password_hash", ""),
            "campaigns": existing.get("campaigns", []),
            "order": existing.get("order", self._next_order(list(clients.values()))),
        }
        if agency_slug:
            for a in doc["agencies"]:
                keys = a.get("client_keys", [])
                if a["slug"] == agency_slug:
                    if key not in keys:
                        a["client_keys"] = keys + [key]
                elif key in keys:
                    a["client_keys"] = [k for k in keys if k != key]
        self._save(doc)

    def remove_client(self, key):
        doc = self._load()
        for a in doc.get("agencies", []):
            if key in a.get("client_keys", []):
                a["client_keys"] = [k for k in a["client_keys"] if k != key]
        self._save(doc)  # keep the client doc so its password/url survive; just detach

    def set_campaign(self, client_key, index, name, path, status):
        doc = self._load()
        c = doc.get("clients", {}).get(client_key)
        if not c:
            raise ValueError("unknown client")
        camps = list(c.get("campaigns", []))
        cm = {"name": name, "path": path, "status": status}
        i = None if (index is None or index == "") else int(index)
        if i is None or i < 0 or i >= len(camps):   # guard BOTH bounds — a negative index must not wrap
            camps.append(cm)
        else:
            camps[i] = cm
        c["campaigns"] = camps
        self._save(doc)

    def delete_campaign(self, client_key, index):
        doc = self._load()
        c = doc.get("clients", {}).get(client_key)
        if not c:
            return
        camps = list(c.get("campaigns", []))
        i = int(index)
        if 0 <= i < len(camps):
            camps.pop(i)
        c["campaigns"] = camps
        self._save(doc)

    # ---- super-admin (god-mode): reveal + rotate every PLATFORM password ----
    # (Dashboard/standalone passwords live in Secret Manager — those are revealed/rotated in main.py,
    #  not here. These three setters cover the passwords the registry owns.)
    def set_admin_password(self, pw):
        doc = self._load()
        doc["admin_password_hash"] = hash_pw(pw)
        doc["admin_password_plain"] = pw
        self._save(doc)

    def set_super_password(self, pw):
        doc = self._load()
        doc["super_admin_password_hash"] = hash_pw(pw)
        doc["super_admin_password_plain"] = pw
        self._save(doc)

    def set_agency_password(self, slug, pw):
        doc = self._load()
        for a in doc.get("agencies", []):
            if a.get("slug") == slug:
                a["password_hash"] = hash_pw(pw)
                a["password_plain"] = pw
                self._save(doc)
                return True
        return False

    def get_super_state(self):
        """Everything the god-mode console reveals. Dashboard (standalone) passwords are filled in
        by main.py from Secret Manager; here we surface the registry-owned passwords in clear."""
        doc = self._load()
        clients = doc.get("clients", {})
        agencies = [{
            "name": a["name"], "slug": a["slug"],
            "password": a.get("password_plain", ""), "has_pw": bool(a.get("password_hash")),
            "client_count": len(a.get("client_keys", [])),
        } for a in sorted(doc.get("agencies", []), key=lambda a: a.get("order", 0))]
        dashboards = [{
            "key": k, "name": c["name"], "slug": c.get("slug", k),
            "status": c.get("status", "active"), "url": c.get("url", ""),
            "note": c.get("note", ""),
        } for k, c in sorted(clients.items(), key=lambda kv: kv[1].get("order", 0))]
        # Which agency owns each dashboard, so the console can group them per agency (100% Digital,
        # Transmission, …) instead of one flat list. Agencies keep their registry `order`; a client
        # in no agency (stt/hireright) falls into a trailing "Unassigned" group.
        ordered_agencies = sorted(doc.get("agencies", []), key=lambda a: a.get("order", 0))
        key_to_agency = {}
        for a in ordered_agencies:
            for ck in a.get("client_keys", []):
                key_to_agency.setdefault(ck, {"name": a["name"], "slug": a["slug"]})
        for d in dashboards:
            ag = key_to_agency.get(d["key"])
            d["agency_slug"] = ag["slug"] if ag else ""
            d["agency_name"] = ag["name"] if ag else ""
        # Sort within each group so dashboards WITH a live dashboard sit on top, structure-only
        # previews (coming_soon but deployed → openable by super admin) next, and clients with no
        # dashboard at all fall to the bottom (easy to spot). Stable → preserves order within a tier.
        def _tier(d):
            if d.get("status") == "active" and d.get("url"):
                return 0                       # live dashboard
            if d.get("url"):
                return 1                       # structure preview (deployed, not live)
            return 2                           # no dashboard yet
        dashboard_groups = []
        for a in ordered_agencies:
            members = sorted([d for d in dashboards if d["agency_slug"] == a["slug"]], key=_tier)
            if members:
                dashboard_groups.append({"name": a["name"], "slug": a["slug"], "dashboards": members})
        unassigned_dash = sorted([d for d in dashboards if not d["agency_slug"]], key=_tier)
        if unassigned_dash:
            dashboard_groups.append({"name": "Unassigned", "slug": "", "dashboards": unassigned_dash})
        agency_names = {a["slug"]: a["name"] for a in agencies}
        client_names = {d["key"]: d["name"] for d in dashboards}
        users = []
        for u in self.list_users():
            scope = ""
            if u["role"] == "agency":
                scope = agency_names.get(u["agency_slug"], u["agency_slug"])
            elif u["role"] == "client":
                scope = client_names.get(u["client_key"], u["client_key"])
            users.append({"email": u["email"], "role": u["role"], "scope": scope,
                          "seed": u["seed"], "agency_slug": u["agency_slug"],
                          "client_key": u["client_key"]})
        return {
            "admin_password": doc.get("admin_password_plain", ""),
            "admin_has": bool(doc.get("admin_password_hash")),
            "super_password": doc.get("super_admin_password_plain", ""),
            "super_has": bool(doc.get("super_admin_password_hash")),
            "agencies": agencies, "dashboards": dashboards,
            "dashboard_groups": dashboard_groups, "users": users,
        }

    def backfill_plaintext(self, candidates):
        """Self-heal a hash-only registry so the super-admin console can REVEAL passwords.

        A live registry seeded before this feature stores passwords only as one-way hashes. For each
        such password, if a known candidate plaintext (from config.py — the documented seed values)
        verifies against the stored hash, persist it as the recoverable `*_plain`. Anything rotated
        away from its seed value won't match, stays hidden, and is set explicitly via the UI.

        candidates: {'admin': pw, 'super': pw, 'agency:<slug>': pw, 'client:<key>': pw}. Idempotent;
        a couple of pbkdf2 checks on first super-admin load, then a no-op once `*_plain` is filled."""
        doc = self._load()
        changed = False
        if not doc.get("admin_password_plain") and candidates.get("admin") \
                and verify_pw(candidates["admin"], doc.get("admin_password_hash", "")):
            doc["admin_password_plain"] = candidates["admin"]; changed = True
        if not doc.get("super_admin_password_plain") and candidates.get("super") \
                and verify_pw(candidates["super"], doc.get("super_admin_password_hash", "")):
            doc["super_admin_password_plain"] = candidates["super"]; changed = True
        for a in doc.get("agencies", []):
            cand = candidates.get(f"agency:{a.get('slug')}")
            if not a.get("password_plain") and cand and verify_pw(cand, a.get("password_hash", "")):
                a["password_plain"] = cand; changed = True
        for k, c in doc.get("clients", {}).items():
            cand = candidates.get(f"client:{k}")
            if not c.get("password_plain") and cand and verify_pw(cand, c.get("password_hash", "")):
                c["password_plain"] = cand; changed = True
        if changed:
            self._save(doc)
        return changed
