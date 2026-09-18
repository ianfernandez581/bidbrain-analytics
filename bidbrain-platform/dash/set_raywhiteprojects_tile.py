r"""Surgically set the Ray White Projects tile in the LIVE platform registry - WITHOUT a full
re-seed (so it cannot clobber agency/client edits made through the admin UI).

`seed_registry.py --force` rewrites every agency + client from config.py; this instead does a
single targeted upsert against the live registry JSON in GCS: it attaches the `raywhiteprojects`
client to the 100% Digital agency, sets its status/url/note, and gives it one campaign row.
Idempotent - safe to re-run. (config.py is still the source of truth in code; this just makes the
change show up on the running site now, the same way the admin UI would.)

The constants below are the desired STATE. The Monair campaign goes live 2026-09-25 and GA4 + GTM
are not installed on monair.com.au yet, so STATUS is "coming_soon" with the placeholder NOTE - the
tile renders with the greyed COMING SOON chip and the "Dashboard isn't live yet" blurb, exactly
like Bell Shakespeare, Next Smile, Geyer Valmont, Lacevo and Burnet, and a super admin can still
open the deployed preview via "Open preview ->".

To flip it LIVE once the feeds are connected: set STATUS = "active", NOTE = "" and the campaign
tuple's status to "active", then re-run. (That is precisely how set_caltex_tile.py went from the
placeholder to live on 2026-07-30 - it began life as add_caltex_placeholder.py.)

KEY vs SLUG. KEY is "raywhiteprojects" and the registry SLUG is "raywhite-projects". They differ
on purpose: every infrastructure name derives from the key, and a BigQuery dataset cannot contain
a hyphen, so "client_raywhite-projects" would not be a legal dataset id the day a pipeline lands.
The estate already carries this split (cityperfume / city-perfume, tlm / the-little-marionette,
sophiie / sophiie-ai). The proxy path is keyed on the KEY: /d/raywhiteprojects/.

ONE CAMPAIGN ROW, AND IT IS THE PROJECT. "Monair, Greenwich" is the first campaign, not the
client - Ray White Projects is expected to run more on the same account. The dashboard treats
project as a DIMENSION (meta.projects plus a project column on every fact row, the client_geocon
pattern), so a second project is a payload change plus one more `set_campaign` row here. It is
NOT a second registry client and NOT a second dashboard.

Run against the live registry as an account with write access to the platform bucket
(ian@100.digital) - NOT charles@ (no perms). PowerShell:

    $env:CLOUDSDK_CORE_ACCOUNT="ian@100.digital"
    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\set_raywhiteprojects_tile.py --yes

Without --yes it prints what it WOULD do and the current state, then exits (dry run).

NOTE - client ACCESS is separate from this tile. The registry keeps no dashboard password for
raywhiteprojects yet (`password_hash` is empty). While the tile is coming_soon that is correct:
only a super admin should be opening the preview. When it goes live, either set the dashboard
password in the SUPER-ADMIN console (it reveals + rotates) or grant each named person's
Google/Microsoft email to this dashboard in that console's sign-in access panel. Agency-level
access (the 100% Digital password) would expose every other 100% Digital client, so do not hand
that out - and that matters more than usual here, because the DEVELOPER (Realside) is a separate
stakeholder who may need a login of their own. Per-email grants are how to give them one today;
a genuinely narrower VIEW needs the role in the SSO token (see the client README).

NOTE - Ray White Projects is attached to 100% Digital ONLY. It is deliberately absent from the
`extrablack` agency: that is an EXTERNAL tenant, and dual visibility there is a per-client decision
(geocon / resetdata / geyervalmont), never a default. It would also strip the staff Internal notes
tab, which is where this dashboard records which feeds are still pending and which plan figures
are still placeholders.
"""
import sys

from store import Store, _BACKEND

AGENCY = "x100-digital"
KEY = "raywhiteprojects"
NAME = "Ray White Projects"
SLUG = "raywhite-projects"
STATUS = "coming_soon"          # greyed COMING SOON chip. ("active" = openable tile.)
URL = "https://raywhiteprojects-dash-516554645957.australia-southeast1.run.app/"
NOTE = "Dashboard isn't live yet - the structure is ready."
CAMPAIGN = ("Monair, Greenwich", "/", "coming_soon")


def main(write: bool):
    if _BACKEND == "memory":
        print("PLATFORM_BACKEND=memory - nothing to write (in-memory store).")
        return
    st = Store()
    existing = st.get_client(KEY)
    agency = st.get_agency(AGENCY)
    if not agency:
        raise SystemExit(f"agency '{AGENCY}' not found in the live registry - aborting (nothing changed).")
    attached = KEY in agency.get("client_keys", [])
    print(f"live registry: {KEY} exists={bool(existing)} | attached to {AGENCY}={attached}")
    if not write:
        print("\nDRY RUN. Re-run with --yes to write:")
        print(f"  + upsert client '{KEY}' ({NAME}, slug={SLUG!r}, status={STATUS}, url={URL!r}, note={NOTE!r}) "
              f"into agency '{AGENCY}'")
        print(f"  + set campaign {CAMPAIGN}")
        return
    # show_pending_row=True is passed EXPLICITLY: upsert_client only PRESERVES that flag, and a
    # client created through this surgical path has no prior value to preserve (seed_registry.py,
    # the only other writer, never runs for it). Without it the Data Accuracy tab shows no row at
    # all for Ray White Projects, rather than the honest greyed "awaiting connection" one. Drop it
    # to False in the same edit that flips STATUS to "active", when a real pipeline starts
    # reporting freshness for itself.
    st.upsert_client(agency_slug=AGENCY, key=KEY, name=NAME, slug=SLUG, status=STATUS, url=URL, note=NOTE,
                     show_pending_row=True)
    st.set_campaign(KEY, 0, *CAMPAIGN)     # index 0 -> replace-or-append (idempotent)
    c = st.get_client(KEY)
    ag = st.get_agency(AGENCY)
    print(f"\nDONE. {KEY} -> status={c['status']} | campaigns={c.get('campaigns')} "
          f"| in {AGENCY}={KEY in ag.get('client_keys', [])}")
    print("The Ray White Projects tile now shows on the 100% Digital portal with the preview treatment.")


if __name__ == "__main__":
    main(write="--yes" in sys.argv)
