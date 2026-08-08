r"""Surgically enable the EXTRABLACK agency portal in the LIVE platform registry — WITHOUT a full
re-seed (so it can't clobber agency/client edits made through the admin UI). Same pattern as
set_caltex_tile.py.

What it writes (idempotent — safe to re-run):
  1. Client `geyervalmont` — COMING SOON tile (no dashboard yet), one /workplace campaign row,
     and `show_pending_row: true` (the greyed "awaiting connection" row on Data Accuracy).
  2. Agency `extrablack` — client_keys [geocon, resetdata, geyervalmont] and the portal flags
     show_sync=False, show_grid_brain=False, internal_notes=False, google_allowlist=[].
     DUAL VISIBILITY: geocon + resetdata are ADDED to extrablack's client_keys and NEVER removed
     from 100% Digital's (one client record, referenced by two agencies). This script asserts the
     100% Digital memberships are intact and aborts if not.
  3. The agency password — ONLY when the AGENCY_EXTRABLACK_PW env var is set (never a committed
     literal, never printed). Without it a new agency is created hash-less = login fails closed;
     set it later here or in the super-admin console. An existing hash is kept unless the env var
     is set (setting it rotates).

CAVEAT — the admin UI's client "Edit" form single-homes: saving geocon/resetdata from the admin
tree with an agency selected will strip the OTHER agency's membership (store.upsert_client's
detach loop). Re-run this script to restore dual visibility if that happens.

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    $env:AGENCY_EXTRABLACK_PW="<the real password - from a password manager, not the repo>"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\enable_extrablack.py --yes

Without --yes it prints what it WOULD do and the current state, then exits (dry run).
"""
import os
import sys

from store import Store, hash_pw, _BACKEND

AGENCY_SLUG = "extrablack"
AGENCY_NAME = "Extrablack"
DUAL_HOME = "x100-digital"                       # geocon/resetdata's existing agency — never touched
DUAL_CLIENTS = ["geocon", "resetdata"]
NEW_CLIENT = {
    "key": "geyervalmont", "name": "Geyer Valmont", "slug": "geyer-valmont",
    "status": "coming_soon", "url": "",
    "note": "Dashboard in build - the structure is on its way.",
    "show_pending_row": True,
    "campaigns": [{"name": "Workplace", "path": "/workplace", "status": "coming_soon"}],
}
AGENCY_FLAGS = {"show_sync": False, "show_grid_brain": False,
                "internal_notes": False, "google_allowlist": []}


def main(write: bool):
    if _BACKEND == "memory":
        print("PLATFORM_BACKEND=memory — nothing to write (in-memory store).")
        return
    st = Store()
    doc = st._load()

    home = next((a for a in doc.get("agencies", []) if a.get("slug") == DUAL_HOME), None)
    if not home:
        raise SystemExit(f"agency '{DUAL_HOME}' not found in the live registry — aborting (nothing changed).")
    missing = [k for k in DUAL_CLIENTS if k not in home.get("client_keys", [])]
    if missing:
        raise SystemExit(f"{missing} not in '{DUAL_HOME}' client_keys — the live registry doesn't look "
                         "like expected; aborting (nothing changed).")
    for k in DUAL_CLIENTS:
        if k not in doc.get("clients", {}):
            raise SystemExit(f"client '{k}' missing from the live registry — aborting (nothing changed).")

    xb = next((a for a in doc.get("agencies", []) if a.get("slug") == AGENCY_SLUG), None)
    gv = doc.get("clients", {}).get(NEW_CLIENT["key"])
    pw = os.environ.get("AGENCY_EXTRABLACK_PW", "")
    print(f"live registry: extrablack agency exists={bool(xb)} | geyervalmont exists={bool(gv)} "
          f"| password env set={bool(pw)}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{NEW_CLIENT['key']}' (coming_soon, show_pending_row, /workplace campaign)")
        print(f"  + upsert agency '{AGENCY_SLUG}' with clients {DUAL_CLIENTS + [NEW_CLIENT['key']]} "
              f"and flags {AGENCY_FLAGS}")
        print(f"  + {'SET the agency password from AGENCY_EXTRABLACK_PW' if pw else 'leave the password as-is (env not set)'}")
        print(f"  + '{DUAL_HOME}' is left untouched (dual visibility)")
        return

    # 1. geyervalmont client (create or refresh the placeholder fields; keep any live extras).
    clients = doc.setdefault("clients", {})
    existing = clients.get(NEW_CLIENT["key"], {})
    merged = dict(existing)
    merged.update(NEW_CLIENT)
    merged.setdefault("password_hash", "")
    merged.setdefault("password_plain", "")
    merged.setdefault("order", max([c.get("order", 0) for c in clients.values()], default=-1) + 1)
    clients[NEW_CLIENT["key"]] = merged

    # 2. extrablack agency: create or update IN PLACE (never touches other agencies' client_keys).
    keys = DUAL_CLIENTS + [NEW_CLIENT["key"]]
    if xb is None:
        xb = {"name": AGENCY_NAME, "slug": AGENCY_SLUG, "password_hash": "", "password_plain": "",
              "client_keys": [], "order": max([a.get("order", 0) for a in doc.get("agencies", [])],
                                              default=-1) + 1}
        doc.setdefault("agencies", []).append(xb)
    xb["name"] = AGENCY_NAME
    xb.update(AGENCY_FLAGS)
    for k in keys:
        if k not in xb.setdefault("client_keys", []):
            xb["client_keys"].append(k)

    # 3. password (only when the env supplies one — rotating is explicit, never accidental).
    if pw:
        xb["password_hash"] = hash_pw(pw)
        xb["password_plain"] = pw   # recoverable copy for the super-admin console, like every agency

    st._save(doc)
    ag = st.get_agency(AGENCY_SLUG)
    hm = st.get_agency(DUAL_HOME)
    print(f"\nDONE. extrablack clients={ag.get('client_keys')} | flags="
          f"{ {k: ag.get(k) for k in AGENCY_FLAGS} } | password set={bool(ag.get('password_hash'))}")
    print(f"'{DUAL_HOME}' still holds {[k for k in DUAL_CLIENTS if k in hm.get('client_keys', [])]} (untouched).")
    print("Login page: https://dashboards.bidbrain.ai/extrablack")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
