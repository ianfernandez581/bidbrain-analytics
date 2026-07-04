r"""Surgically add the Caltex 'COMING SOON' tile to the LIVE platform registry — WITHOUT a full
re-seed (so it can't clobber agency/client edits made through the admin UI).

`seed_registry.py --force` rewrites every agency + client from config.py; this instead does a single
targeted upsert against the live registry JSON in GCS: it attaches a `caltex` client (status
coming_soon) to the 100% Digital agency and gives it one campaign row. Idempotent — safe to re-run.
(config.py is still the source of truth in code; this just makes the change show up on the running
site now, the same way the admin UI would.)

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital) — NOT charles@ (no perms). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\add_caltex_placeholder.py --yes

Without --yes it prints what it WOULD do and the current caltex state, then exits (dry run).

To surface the built placeholder dashboard as an OPENABLE tile later (after deploy_caltex.ps1 stands
up the caltex-dash service), re-run the upsert with status 'active' + the run.app url, or just do it
in the admin UI.
"""
import os
import sys

from store import Store, _BACKEND

AGENCY = "x100-digital"
KEY = "caltex"
NAME = "Caltex"
STATUS = "coming_soon"          # -> greyed "COMING SOON" tile (no dead link). Flip to "active" post-deploy.
URL = ""                        # set to the caltex-dash run.app url when going active
CAMPAIGN = ("Paid Media", "/paid-media", "coming_soon")


def main(write: bool):
    if _BACKEND == "memory":
        print("PLATFORM_BACKEND=memory — nothing to write (in-memory store).")
        return
    st = Store()
    existing = st.get_client(KEY)
    agency = st.get_agency(AGENCY)
    if not agency:
        raise SystemExit(f"agency '{AGENCY}' not found in the live registry — aborting (nothing changed).")
    attached = KEY in agency.get("client_keys", [])
    print(f"live registry: caltex exists={bool(existing)} | attached to {AGENCY}={attached}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{KEY}' ({NAME}, status={STATUS}) into agency '{AGENCY}'")
        print(f"  + set campaign {CAMPAIGN}")
        return
    st.upsert_client(agency_slug=AGENCY, key=KEY, name=NAME, slug=KEY, status=STATUS, url=URL)
    st.set_campaign(KEY, 0, *CAMPAIGN)     # index 0 -> replace-or-append (idempotent)
    c = st.get_client(KEY)
    ag = st.get_agency(AGENCY)
    print(f"\nDONE. caltex -> status={c['status']} | campaigns={c.get('campaigns')} "
          f"| in {AGENCY}={KEY in ag.get('client_keys', [])}")
    print("The 'COMING SOON' Caltex tile is now live on the 100% Digital portal.")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
