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
        # email -> role map for Google sign-in (parallel to the password gate). See resolve_email.
        "google_allowlist": {e.strip().lower(): dict(v) for e, v in getattr(seed, "GOOGLE_ALLOWLIST", {}).items()},
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
            "url": c.get("url", ""), "password_hash": hash_pw(pw), "password_plain": pw,
            "campaigns": [dict(cm) for cm in c.get("campaigns", [])], "order": i,
        }
    for k in seed.UNASSIGNED_CLIENTS:
        doc["clients"].setdefault(k, {
            "key": k, "name": k.upper(), "slug": k, "status": "active",
            "url": seed._runapp(k), "password_hash": "", "password_plain": "",
            "campaigns": [], "order": 99,
        })
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
                "agencies": [], "clients": {}, "google_allowlist": {}}

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
        doc.setdefault("google_allowlist", {})
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
                })
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

    def resolve_email(self, email):
        """Google-sign-in twin of resolve_password: map a VERIFIED Google email to the SAME role
        tuple ('superadmin'|'admin'|'agency'|'client', payload) the password flow returns, so the
        caller sets an identical session. Returns (None, None) for any email not on the allow-list,
        or whose mapped agency/client no longer exists (a deleted target fails CLOSED).

        Allow-list entry shapes (see config.GOOGLE_ALLOWLIST / set_allowed_email):
            {"kind": "admin"}            {"kind": "superadmin"}
            {"kind": "agency", "slug": "<agency-slug>"}
            {"kind": "client", "key": "<client-key>"}"""
        if not email:
            return None, None
        doc = self._load()
        entry = doc.get("google_allowlist", {}).get(email.strip().lower())
        if not entry:
            return None, None
        kind = entry.get("kind")
        if kind in ("admin", "superadmin"):
            return kind, None
        if kind == "agency":
            a = next((a for a in doc.get("agencies", []) if a.get("slug") == entry.get("slug")), None)
            return ("agency", a) if a else (None, None)
        if kind == "client":
            c = doc.get("clients", {}).get(entry.get("key"))
            return ("client", c) if c else (None, None)
        return None, None

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

    def upsert_client(self, agency_slug, key, name, slug, status, url):
        doc = self._load()
        # Validate the target agency BEFORE writing, so a stale/deleted agency_slug can't orphan it.
        if agency_slug and not any(a["slug"] == agency_slug for a in doc.get("agencies", [])):
            raise ValueError(f"unknown agency '{agency_slug}'")
        clients = doc.setdefault("clients", {})
        existing = clients.get(key, {})
        clients[key] = {
            "key": key, "name": name, "slug": slug, "status": status, "url": url,
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

    # ---- Google sign-in allow-list (email -> role) -------------------------------------------
    def list_allowed_emails(self):
        """The whole allow-list as {email: {kind, slug?|key?}} (for the admin UI)."""
        return dict(self._load().get("google_allowlist", {}))

    def set_allowed_email(self, email, kind, ref=""):
        """Add/overwrite one allow-list entry. kind in admin|superadmin|agency|client; ref is the
        agency slug (agency) or client key (client), ignored for admin/superadmin. Validates the
        target exists so you can't strand an email on a non-existent agency/client."""
        email = (email or "").strip().lower()
        if not email or kind not in ("admin", "superadmin", "agency", "client"):
            raise ValueError("email required and kind must be admin|superadmin|agency|client")
        doc = self._load()
        entry = {"kind": kind}
        if kind == "agency":
            if not any(a.get("slug") == ref for a in doc.get("agencies", [])):
                raise ValueError(f"unknown agency '{ref}'")
            entry["slug"] = ref
        elif kind == "client":
            if ref not in doc.get("clients", {}):
                raise ValueError(f"unknown client '{ref}'")
            entry["key"] = ref
        doc.setdefault("google_allowlist", {})[email] = entry
        self._save(doc)

    def remove_allowed_email(self, email):
        email = (email or "").strip().lower()
        doc = self._load()
        if email in doc.get("google_allowlist", {}):
            del doc["google_allowlist"][email]
            self._save(doc)

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
        } for k, c in sorted(clients.items(), key=lambda kv: kv[1].get("order", 0))]
        # Google sign-in allow-list, each with a friendly target label for the console.
        agency_names = {a.get("slug"): a.get("name") for a in doc.get("agencies", [])}
        allowlist = []
        for email, e in sorted(doc.get("google_allowlist", {}).items()):
            kind = e.get("kind", "")
            if kind == "agency":
                target = agency_names.get(e.get("slug"), e.get("slug", ""))
            elif kind == "client":
                target = (clients.get(e.get("key")) or {}).get("name", e.get("key", ""))
            else:
                target = ""
            allowlist.append({"email": email, "kind": kind,
                              "ref": e.get("slug") or e.get("key") or "", "target": target})
        return {
            "admin_password": doc.get("admin_password_plain", ""),
            "admin_has": bool(doc.get("admin_password_hash")),
            "super_password": doc.get("super_admin_password_plain", ""),
            "super_has": bool(doc.get("super_admin_password_hash")),
            "agencies": agencies, "dashboards": dashboards,
            "google_allowlist": allowlist,
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
