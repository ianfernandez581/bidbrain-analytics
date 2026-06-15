"""Seed Firestore from config.py — run ONCE at standup (and only deliberately after).

    .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_firestore.py [--force]

Without --force it refuses to overwrite a collection that already has documents (so it never
clobbers admin edits made through the live UI). With --force it re-writes every agency/client
from config.py — losing divergent live edits to name/slug/status/url/campaigns. Two safety carve-outs:
a client's dashboard password_hash is PRESERVED unless a `<KEY>_DASH_PW` env is given, and --force
does NOT prune — agencies/clients created via the admin UI but absent from config.py survive.
Passwords are hashed (pbkdf2) before write; the plaintext seed values never reach Firestore.

Per-client dashboard passwords: the seed leaves them blank unless you provide them via
`<KEY>_DASH_PW` env vars (e.g. CITYPERFUME_DASH_PW). The real values already live in the
`<c>-dash-password` secrets; mirror them here only if you want a single-dashboard login at the
platform to resolve that client. The admin/agency passwords come from config.py (env-overridable).

Run with GOOGLE_APPLICATION_CREDENTIALS / ADC pointed at the bidbrain-analytics project, or
locally against the in-memory backend by setting PLATFORM_BACKEND=memory (no-op, nothing to seed).
"""
import sys
import os

import config as seed
from store import hash_pw, _BACKEND


def main(force: bool):
    if _BACKEND == "memory":
        print("PLATFORM_BACKEND=memory — nothing to seed (the in-memory store loads config.py at boot).")
        return

    from google.cloud import firestore
    db = firestore.Client()

    if not force:
        for coll in ("platform_agencies", "platform_clients", "platform_meta"):
            if next(db.collection(coll).limit(1).stream(), None) is not None:
                print(f"Refusing to seed: collection '{coll}' already has data. Re-run with --force to overwrite.")
                return

    # admin password
    db.collection("platform_meta").document("config").set(
        {"admin_password_hash": hash_pw(seed.ADMIN_PW)}
    )
    print("seeded platform_meta/config (admin password)")

    # clients. NOTE: --force overwrites name/slug/status/url/campaigns from config.py, but a
    # client dashboard password is PRESERVED unless a `<KEY>_DASH_PW` env is supplied — otherwise a
    # re-seed would blank a password set/rotated directly in Firestore and break that single-dash login.
    for i, (key, c) in enumerate(seed.CLIENTS.items()):
        seed_pw = seed.CLIENT_PASSWORDS.get(key, "")
        prior = db.collection("platform_clients").document(key).get()
        prior_hash = (prior.to_dict() or {}).get("password_hash", "") if prior.exists else ""
        db.collection("platform_clients").document(key).set({
            "key": key, "name": c["name"], "slug": c["slug"], "status": c["status"],
            "url": c.get("url", ""),
            "password_hash": hash_pw(seed_pw) if seed_pw else prior_hash,
            "campaigns": [dict(cm) for cm in c.get("campaigns", [])],
            "order": i,
        })
        print(f"seeded platform_clients/{key}")

    # unassigned clients (reachable only by their own dashboard password)
    for k in seed.UNASSIGNED_CLIENTS:
        if k in seed.CLIENTS:
            continue
        db.collection("platform_clients").document(k).set({
            "key": k, "name": k.upper(), "slug": k, "status": "active",
            "url": "", "password_hash": "", "campaigns": [], "order": 99,
        })
        print(f"seeded platform_clients/{k} (unassigned)")

    # agencies
    for i, a in enumerate(seed.AGENCIES):
        db.collection("platform_agencies").document(a["slug"]).set({
            "name": a["name"], "slug": a["slug"],
            "password_hash": hash_pw(a["password"]),
            "client_keys": list(a["clients"]),
            "order": i,
        })
        print(f"seeded platform_agencies/{a['slug']}")

    print("\nDone. The platform now reads this from Firestore; further edits go through the admin UI.")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
