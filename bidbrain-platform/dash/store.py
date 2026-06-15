"""Persistence + password resolution for the platform front-door.

Backend = Firestore (native mode), collections:
  platform_agencies/<slug>  {name, slug, password_hash, client_keys[], order}
  platform_clients/<key>     {key, name, slug, status, url, password_hash, campaigns[], order}
  platform_meta/config       {admin_password_hash}

Set env `PLATFORM_BACKEND=memory` to run without Firestore (local dev / unit checks): the
store then lives in-process, seeded from config.py, and edits are lost on restart.

Passwords are never stored in clear: pbkdf2_hmac (stdlib, no extra dependency) with a random
salt. `resolve_password()` is the login brain — it maps a typed password to admin / a specific
agency / a single client, and is constant-time per candidate via hmac.compare_digest.
"""
import os
import hmac
import hashlib
import secrets as _secrets

import config as seed

_BACKEND = os.environ.get("PLATFORM_BACKEND", "firestore").lower()

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


# =========================================================================================
class Store:
    def __init__(self):
        self._mem = None
        if _BACKEND == "memory":
            self._db = None
            self._load_memory_from_seed()
        else:
            from google.cloud import firestore  # lazy: keep off the import path in memory mode
            self._db = firestore.Client()

    # ---- collection handles ----
    def _ag(self):
        return self._db.collection("platform_agencies")

    def _cl(self):
        return self._db.collection("platform_clients")

    def _meta(self):
        return self._db.collection("platform_meta").document("config")

    # ---- in-memory backend (dev) ----
    def _load_memory_from_seed(self):
        self._mem = {"agencies": {}, "clients": {}, "admin_password_hash": hash_pw(seed.ADMIN_PW)}
        for i, a in enumerate(seed.AGENCIES):
            self._mem["agencies"][a["slug"]] = {
                "name": a["name"], "slug": a["slug"],
                "password_hash": hash_pw(a["password"]),
                "client_keys": list(a["clients"]), "order": i,
            }
        for i, (k, c) in enumerate(seed.CLIENTS.items()):
            self._mem["clients"][k] = {
                "key": k, "name": c["name"], "slug": c["slug"], "status": c["status"],
                "url": c.get("url", ""), "password_hash": hash_pw(seed.CLIENT_PASSWORDS.get(k, "")),
                "campaigns": [dict(cm) for cm in c.get("campaigns", [])], "order": i,
            }
        for k in seed.UNASSIGNED_CLIENTS:
            self._mem["clients"].setdefault(k, {
                "key": k, "name": k.upper(), "slug": k, "status": "active",
                "url": "", "password_hash": "", "campaigns": [], "order": 99,
            })

    # ---- reads ----
    def _all_agencies(self):
        if self._mem is not None:
            return sorted(self._mem["agencies"].values(), key=lambda a: a.get("order", 0))
        return sorted((d.to_dict() for d in self._ag().stream()), key=lambda a: a.get("order", 0))

    def _all_clients(self):
        if self._mem is not None:
            return {k: dict(v) for k, v in self._mem["clients"].items()}
        return {d.id: d.to_dict() for d in self._cl().stream()}

    def _client(self, key):
        if self._mem is not None:
            return self._mem["clients"].get(key)
        d = self._cl().document(key).get()
        return d.to_dict() if d.exists else None

    def get_agency(self, slug):
        if not slug:
            return None
        if self._mem is not None:
            return self._mem["agencies"].get(slug)
        d = self._ag().document(slug).get()
        return d.to_dict() if d.exists else None

    def _admin_hash(self):
        if self._mem is not None:
            return self._mem["admin_password_hash"]
        d = self._meta().get()
        return (d.to_dict() or {}).get("admin_password_hash", "") if d.exists else ""

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
        """Return (kind, payload): ('admin', None) | ('agency', agency_dict) | ('client', client_dict) | (None, None)."""
        if not password:
            return None, None
        if verify_pw(password, self._admin_hash()):
            return "admin", None
        for a in self._all_agencies():
            if verify_pw(password, a.get("password_hash", "")):
                return "agency", a
        for key, c in self._all_clients().items():
            if verify_pw(password, c.get("password_hash", "")):
                return "client", c
        return None, None

    def active_client_keys(self):
        """Every live (status=='active') client key — across agencies AND unassigned. The admin
        SSO grant uses this so it covers live-but-unassigned dashboards (hireright) and excludes
        coming_soon ones (bellshakespeare/geocon), rather than the nested agency-tree shape."""
        return [k for k, c in self._all_clients().items() if c.get("status") == "active"]

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

    def client_keys_for_agency_password_set(self):
        pass  # reserved

    # ---- writes (admin CRUD) ----
    def _set_agency(self, slug, doc):
        if self._mem is not None:
            self._mem["agencies"][slug] = doc
        else:
            self._ag().document(slug).set(doc)

    def _del_agency(self, slug):
        if self._mem is not None:
            self._mem["agencies"].pop(slug, None)
        else:
            self._ag().document(slug).delete()

    def _set_client(self, key, doc):
        if self._mem is not None:
            self._mem["clients"][key] = doc
        else:
            self._cl().document(key).set(doc)

    def upsert_agency(self, orig_slug, name, slug, password):
        existing = None
        if self._mem is not None:
            existing = self._mem["agencies"].get(orig_slug)
        else:
            d = self._ag().document(orig_slug).get() if orig_slug else None
            existing = d.to_dict() if (d and d.exists) else None
        doc = {
            "name": name, "slug": slug,
            "password_hash": hash_pw(password) if password else (existing or {}).get("password_hash", ""),
            "client_keys": (existing or {}).get("client_keys", []),
            "order": (existing or {}).get("order", self._next_order("agencies")),
        }
        if orig_slug and orig_slug != slug:
            self._del_agency(orig_slug)
        self._set_agency(slug, doc)

    def delete_agency(self, slug):
        self._del_agency(slug)  # clients persist; they fall into "unassigned"

    def _next_order(self, kind):
        items = self._all_agencies() if kind == "agencies" else list(self._all_clients().values())
        return (max([i.get("order", 0) for i in items], default=-1)) + 1

    def upsert_client(self, agency_slug, key, name, slug, status, url):
        # Validate the target agency BEFORE writing anything, so a stale/deleted agency_slug
        # (e.g. a concurrent rename in another tab) can never orphan the client into "unassigned".
        if agency_slug and self.get_agency(agency_slug) is None:
            raise ValueError(f"unknown agency '{agency_slug}'")
        existing = self._client(key) or {}
        doc = {
            "key": key, "name": name, "slug": slug, "status": status, "url": url,
            "password_hash": existing.get("password_hash", ""),
            "campaigns": existing.get("campaigns", []),
            "order": existing.get("order", self._next_order("clients")),
        }
        self._set_client(key, doc)
        if agency_slug:
            self._attach_client(agency_slug, key)

    def _attach_client(self, agency_slug, key):
        # List the key under exactly this agency, removed from others. Guarded (caller already
        # validated), and writes ONLY the agencies whose client_keys actually change.
        if self.get_agency(agency_slug) is None:
            raise ValueError(f"unknown agency '{agency_slug}'")
        for a in self._all_agencies():
            keys = a.get("client_keys", [])
            if a["slug"] == agency_slug:
                if key not in keys:
                    a["client_keys"] = keys + [key]
                    self._set_agency(a["slug"], a)
            elif key in keys:
                a["client_keys"] = [k for k in keys if k != key]
                self._set_agency(a["slug"], a)

    def remove_client(self, key):
        # detach from any agency (keep the client doc so its password/url survive)
        for a in self._all_agencies():
            if key in a.get("client_keys", []):
                a["client_keys"] = [k for k in a["client_keys"] if k != key]
                self._set_agency(a["slug"], a)

    def set_campaign(self, client_key, index, name, path, status):
        c = self._client(client_key)
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
        self._set_client(client_key, c)

    def delete_campaign(self, client_key, index):
        c = self._client(client_key)
        if not c:
            return
        camps = list(c.get("campaigns", []))
        i = int(index)
        if 0 <= i < len(camps):
            camps.pop(i)
        c["campaigns"] = camps
        self._set_client(client_key, c)
