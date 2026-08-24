r"""Attach the HireRight dashboard to the TRANSMISSION agency in the LIVE platform registry —
WITHOUT a full re-seed (so it can't clobber agency/client edits made through the admin UI).

Why this exists: HireRight was the one live dashboard in NO agency (`config.UNASSIGNED_CLIENTS`),
so only superadmin/admin could open it and Transmission's own agency login could not see it — even
though all three of its feeds (DV360, TradeDesk, LinkedIn) have always come off Transmission's
Snowflake share. config.py is the source of truth in code, but the running site reads the registry
blob in GCS, which config.py only SEEDS. This makes the change show up now, the way the admin UI
would. Idempotent — safe to re-run.

`upsert_client` preserves the existing password_hash, campaigns, spend_multipliers and order, and
moves the key out of any other agency's client_keys, so this cannot orphan or duplicate the client.

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital) — NOT charles@ (no perms). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\set_hireright_tile.py --yes

Without --yes it prints what it WOULD do and the current hireright state, then exits (dry run).

NOTE — this grants the TRANSMISSION AGENCY login sight of HireRight. It does not create a HireRight
client login. HireRight's own dashboard password lives in Secret Manager (`hireright-dash-password`);
to let HireRight staff in directly, set/rotate it in the super-admin console or grant their
Google/Microsoft email to this dashboard there. Never hand out the agency password — it opens every
other Transmission client (Cloudflare, MongoDB, Schneider x3, PropTrack, STT).
"""
import sys

from store import Store, _BACKEND

AGENCY = "transmission"
KEY = "hireright"
NAME = "HireRight"
STATUS = "active"               # -> openable tile. ("coming_soon" = greyed COMING SOON chip.)
URL = "https://hireright-dash-516554645957.australia-southeast1.run.app/"
NOTE = ""
CAMPAIGN = ("Paid Media", "/paid-media", "active")


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
    # Which agency (if any) holds it today, so a surprise is visible BEFORE the write.
    holder = next((a["slug"] for a in st._all_agencies() if KEY in a.get("client_keys", [])), None)
    print(f"live registry: hireright exists={bool(existing)} | attached to {AGENCY}={attached} "
          f"| currently in agency={holder or '(none - unassigned)'}")
    if existing:
        print(f"               status={existing.get('status')!r} url={existing.get('url')!r} "
              f"has_password={bool(existing.get('password_hash'))}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{KEY}' ({NAME}, status={STATUS}, url={URL!r}) into agency '{AGENCY}'")
        print(f"  + set campaign {CAMPAIGN}")
        return
    st.upsert_client(agency_slug=AGENCY, key=KEY, name=NAME, slug=KEY, status=STATUS, url=URL, note=NOTE)
    st.set_campaign(KEY, 0, *CAMPAIGN)     # index 0 -> replace-or-append (idempotent)
    c = st.get_client(KEY)
    ag = st.get_agency(AGENCY)
    print(f"\nDONE. hireright -> status={c['status']} | campaigns={c.get('campaigns')} "
          f"| in {AGENCY}={KEY in ag.get('client_keys', [])}")
    print("HireRight is now visible on the Transmission portal.")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
