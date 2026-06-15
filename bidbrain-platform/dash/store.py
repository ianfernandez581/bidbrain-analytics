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
    """The full registry dict built from config.py (seed for a fresh store / the memory backend)."""
    doc = {"admin_password_hash": hash_pw(seed.ADMIN_PW), "agencies": [], "clients": {}}
    for i, a in enumerate(seed.AGENCIES):
        doc["agencies"].append({
            "name": a["name"], "slug": a["slug"],
            "password_hash": hash_pw(a["password"]),
            "client_keys": list(a["clients"]), "order": i,
        })
    for i, (k, c) in enumerate(seed.CLIENTS.items()):
        doc["clients"][k] = {
            "key": k, "name": c["name"], "slug": c["slug"], "status": c["status"],
            "url": c.get("url", ""), "password_hash": hash_pw(seed.CLIENT_PASSWORDS.get(k, "")),
            "campaigns": [dict(cm) for cm in c.get("campaigns", [])], "order": i,
        }
    for k in seed.UNASSIGNED_CLIENTS:
        doc["clients"].setdefault(k, {
            "key": k, "name": k.upper(), "slug": k, "status": "active",
            "url": seed._runapp(k), "password_hash": "", "campaigns": [], "order": 99,
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
        return {"admin_password_hash": "", "agencies": [], "clients": {}}

    def _load(self):
        if self._mem is not None:
            return self._mem
        blob = self._bucket.blob(self._object)
        if not blob.exists():
            return self._empty()
        try:
            doc = json.loads(blob.download_as_bytes())
            doc.setdefault("agencies", [])
            doc.setdefault("clients", {})
            doc.setdefault("admin_password_hash", "")
            return doc
        except Exception:
            return self._empty()

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
        """('admin', None) | ('agency', agency_dict) | ('client', client_dict) | (None, None)."""
        if not password:
            return None, None
        doc = self._load()
        if verify_pw(password, doc.get("admin_password_hash", "")):
            return "admin", None
        for a in sorted(doc.get("agencies", []), key=lambda a: a.get("order", 0)):
            if verify_pw(password, a.get("password_hash", "")):
                return "agency", a
        for key, c in doc.get("clients", {}).items():
            if verify_pw(password, c.get("password_hash", "")):
                return "client", c
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
