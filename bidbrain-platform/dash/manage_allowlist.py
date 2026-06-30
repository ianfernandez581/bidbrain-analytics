r"""Manage the Google sign-in allow-list (email -> role) on the LIVE registry.

"Continue with Google" authorises a verified email by mapping it to a role (admin / agency / client)
in the registry's `google_allowlist`. `config.GOOGLE_ALLOWLIST` is only the SEED — an already-live
registry won't pick it up (seed_registry refuses to clobber a populated registry), so use this CLI to
view and edit the live list without a risky full --force re-seed. (A proper in-UI editor is the
natural follow-up; until then this is the supported path.)

    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"     # + ADC on bidbrain-analytics
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py list
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py add ian@100.digital admin
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py add boss@agency.com agency transmission
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py add v@client.com client schneider
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py remove ian@100.digital
    .\.venv\Scripts\python.exe bidbrain-platform\dash\manage_allowlist.py seed   # merge in any MISSING config entries

`kind` is admin | superadmin | agency | client; `ref` is the agency slug (agency) or client key
(client). `seed` only ADDS emails from config.GOOGLE_ALLOWLIST that aren't already present — it never
overwrites or removes a live entry.
"""
import sys

import config as cfg
from store import Store


def _print_list(store):
    al = store.list_allowed_emails()
    if not al:
        print("(allow-list is empty)")
        return
    for email in sorted(al):
        e = al[email]
        ref = e.get("slug") or e.get("key") or ""
        print(f"  {email:32} {e.get('kind',''):11} {ref}")


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    store = Store()
    cmd = argv[0]
    if cmd == "list":
        _print_list(store)
    elif cmd == "add":
        if len(argv) < 3:
            print("usage: add <email> <kind> [ref]"); return 1
        try:
            store.set_allowed_email(argv[1], argv[2], argv[3] if len(argv) > 3 else "")
        except ValueError as e:
            print(f"error: {e}"); return 1
        print(f"added {argv[1].strip().lower()} -> {argv[2]} {argv[3] if len(argv) > 3 else ''}".rstrip())
        _print_list(store)
    elif cmd == "remove":
        if len(argv) < 2:
            print("usage: remove <email>"); return 1
        store.remove_allowed_email(argv[1])
        print(f"removed {argv[1].strip().lower()}")
        _print_list(store)
    elif cmd == "seed":
        existing = store.list_allowed_emails()
        added = 0
        for email, entry in getattr(cfg, "GOOGLE_ALLOWLIST", {}).items():
            email_l = email.strip().lower()
            if email_l in existing:
                print(f"  skip {email_l} (already present)")
                continue
            store.set_allowed_email(email_l, entry.get("kind"),
                                    entry.get("slug") or entry.get("key") or "")
            print(f"  add  {email_l} -> {entry.get('kind')}")
            added += 1
        print(f"seed complete: {added} added, {len(existing)} left as-is.")
        _print_list(store)
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
