r"""Surgically set the Sophiie AI tile in the LIVE platform registry — WITHOUT a full re-seed (so it
can't clobber agency/client edits made through the admin UI).

`seed_registry.py --force` rewrites every agency + client from config.py; this instead does a single
targeted upsert against the live registry JSON in GCS: it attaches the `sophiie` client to the
100% Digital agency, sets its status/url/note, and gives it one campaign row. Idempotent — safe to
re-run. (config.py is still the source of truth in code; this just makes the change show up on the
running site now, the same way the admin UI would.)

The constants below are the desired STATE. FLIPPED LIVE on 2026-09-05: STATUS is "active", the
placeholder NOTE is cleared and the campaign row names the live Trade Desk buy, so the tile renders
as a normal openable client tile on the 100% Digital portal rather than a greyed COMING SOON chip.
The same change is made in config.py, so a future full re-seed cannot revert it.

To put it BACK to a preview: set STATUS = "coming_soon", restore a NOTE, set the campaign tuple's
status to "coming_soon", and re-run - in both this file and config.py.

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital) — NOT charles@ (no perms). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\set_sophiie_tile.py --yes

Without --yes it prints what it WOULD do and the current sophiie state, then exits (dry run).

NOTE — client ACCESS is separate from this tile, and the tile going ACTIVE does not by itself let
the client in. Set the Sophiie AI dashboard password in the SUPER-ADMIN console (it reveals and
rotates the `sophiie-dash-password` secret), or grant their Google/Microsoft email to this dashboard
in that console's sign-in access panel. Do NOT hand out the 100% Digital agency password: it opens
every other 100% Digital client.
"""
import sys

from store import Store, _BACKEND

AGENCY = "x100-digital"
KEY = "sophiie"
NAME = "Sophiie AI"
STATUS = "active"               # openable client tile. ("coming_soon" = greyed COMING SOON chip.)
URL = "https://sophiie-dash-516554645957.australia-southeast1.run.app/"
NOTE = ""
CAMPAIGN = ("Trade Desk Display", "/paid-media", "active")


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
    print(f"live registry: sophiie exists={bool(existing)} | attached to {AGENCY}={attached}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{KEY}' ({NAME}, status={STATUS}, url={URL!r}, note={NOTE!r}) into agency '{AGENCY}'")
        print(f"  + set campaign {CAMPAIGN}")
        return
    st.upsert_client(agency_slug=AGENCY, key=KEY, name=NAME, slug="sophiie-ai", status=STATUS, url=URL, note=NOTE)
    st.set_campaign(KEY, 0, *CAMPAIGN)     # index 0 -> replace-or-append (idempotent)
    # `show_pending_row` gave the Data Accuracy tab a greyed "awaiting connection" row while this
    # client had no pipeline. It has one now, so the flag is CLEARED here (upsert_client does not
    # own the field, and a stale True would keep printing "awaiting connection" over real checks).
    doc = st._load()
    doc["clients"][KEY].pop("show_pending_row", None)
    st._save(doc)
    c = st.get_client(KEY)
    ag = st.get_agency(AGENCY)
    print(f"\nDONE. sophiie -> status={c['status']} | campaigns={c.get('campaigns')} "
          f"| in {AGENCY}={KEY in ag.get('client_keys', [])}")
    print("The Sophiie AI tile is now ACTIVE on the 100% Digital portal.")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
