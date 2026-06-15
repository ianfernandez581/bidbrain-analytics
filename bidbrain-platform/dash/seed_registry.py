r"""Seed the registry JSON in GCS from config.py — run ONCE at standup (deliberately after).

    $env:GCS_BUCKET="bidbrain-analytics-platform-dash"
    .\.venv\Scripts\python.exe bidbrain-platform\dash\seed_registry.py [--force]

Without --force it refuses to overwrite a registry that already has data (so it never clobbers
admin edits made through the live UI). With --force it re-writes agencies/clients from config.py,
but PRESERVES a client's dashboard password unless config supplies one (`<KEY>_DASH_PW` env) and
does NOT prune admin-created entries absent from config.py. Passwords are hashed (pbkdf2) before
write; the plaintext seed values never reach GCS.

Run with ADC pointed at bidbrain-analytics (the deploy script sets GCS_BUCKET and calls this), or
locally against the in-memory backend by setting PLATFORM_BACKEND=memory (no-op — nothing to seed).
"""
import sys

from store import Store, _BACKEND


def main(force: bool):
    if _BACKEND == "memory":
        print("PLATFORM_BACKEND=memory — nothing to seed (the in-memory store loads config.py at boot).")
        return
    wrote = Store().seed(force=force)
    if wrote:
        print("Seeded the registry from config.py.")
    else:
        print("Registry already has data — refused to overwrite. Re-run with --force to re-seed.")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
