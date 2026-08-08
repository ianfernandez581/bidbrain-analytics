r"""Surgically set the Geyer Valmont tile in the LIVE platform registry — WITHOUT a full re-seed (so
it can't clobber agency/client edits made through the admin UI).

`seed_registry.py --force` rewrites every agency + client from config.py; this instead does a single
targeted upsert against the live registry JSON in GCS: it attaches the `geyervalmont` client to the
100% Digital agency, sets its status/url/note, and gives it one campaign row. Idempotent — safe to
re-run. (config.py is still the source of truth in code; this just makes the change show up on the
running site now, the same way the admin UI would.)

The constants below are the desired STATE. Geyer Valmont's campaigns have NOT launched, so STATUS is
"coming_soon" with the placeholder NOTE — the tile renders with the greyed COMING SOON chip and the
"Dashboard isn't live yet - the structure is ready." blurb, exactly like Bell Shakespeare and Next
Smile Australia, and a super admin can still open the deployed preview via "Open preview →".

To flip it LIVE once the pipeline is connected: set STATUS = "active", NOTE = "" and the campaign
tuple's status to "active", then re-run. (That is precisely how set_caltex_tile.py went from the
placeholder to live on 2026-07-30 — it began life as add_caltex_placeholder.py.)

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital) — NOT charles@ (no perms). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\set_geyervalmont_tile.py --yes

Without --yes it prints what it WOULD do and the current geyervalmont state, then exits (dry run).

NOTE — client ACCESS is separate from this tile. The registry keeps no dashboard password for
geyervalmont yet (`password_hash` is empty). While the tile is coming_soon that is correct: only a
super admin should be opening the preview. When it goes live, either set the Geyer Valmont dashboard
password in the SUPER-ADMIN console (it reveals + rotates) or grant their Google/Microsoft email to
this dashboard in that console's sign-in access panel. Agency-level access (the 100% Digital
password) would expose every other 100% Digital client, so don't hand that out.
"""
import sys

from store import Store, _BACKEND

AGENCY = "x100-digital"
KEY = "geyervalmont"
NAME = "Geyer Valmont"
STATUS = "coming_soon"          # greyed COMING SOON chip. ("active" = openable tile.)
URL = "https://geyervalmont-dash-516554645957.australia-southeast1.run.app/"
NOTE = "Dashboard isn't live yet - the structure is ready."
CAMPAIGN = ("Workplace Design", "/paid-media", "coming_soon")


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
    print(f"live registry: geyervalmont exists={bool(existing)} | attached to {AGENCY}={attached}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{KEY}' ({NAME}, status={STATUS}, url={URL!r}, note={NOTE!r}) into agency '{AGENCY}'")
        print(f"  + set campaign {CAMPAIGN}")
        return
    st.upsert_client(agency_slug=AGENCY, key=KEY, name=NAME, slug=KEY, status=STATUS, url=URL, note=NOTE)
    st.set_campaign(KEY, 0, *CAMPAIGN)     # index 0 -> replace-or-append (idempotent)
    c = st.get_client(KEY)
    ag = st.get_agency(AGENCY)
    print(f"\nDONE. geyervalmont -> status={c['status']} | campaigns={c.get('campaigns')} "
          f"| in {AGENCY}={KEY in ag.get('client_keys', [])}")
    print("The Geyer Valmont tile now shows on the 100% Digital portal with the preview treatment.")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
