"""status-deploy — the privileged "Make this live" worker (Cloud Run job).

Triggered by the platform front-door's Data Accuracy tab when someone edits a client's
definitions and clicks "Make this live". Given DEPLOY_CLIENT=<c> (a per-execution env
override), it:

  1. reads the STAGED definitions  gs://{BUCKET}/definitions/<c>.staged.json
  2. structurally validates them (and keeps the current LIVE copy for rollback)
  3. WRITE_TRUNCATEs the client_<c>.seed_* tables from the staged doc (definitions_seed.py)
  4. smoke-checks the client's views (SELECT COUNT(*)) — the views read the seed tables live,
     so this catches a seed change that would break a view BEFORE anything is promoted
  5. on success: promotes staged -> live, then runs <c>-export + status-export (FORCE_REBUILD=1)
     on smoke failure: re-seeds from the LIVE copy (rollback) and exits non-zero

No view re-apply and NO image rebuild: the views read the seed tables live, so a definition
change is just a seed reload + a job re-run. That is why this needs only BigQuery dataEditor
(seed the tables) + run.invoker (RUN the existing jobs) — RUNNING a job never hits the
iam.serviceaccounts.actAs wall that blocks building/deploying one.

This job's SA (`status-deploy@`) holds the only write IAM; the platform web tier merely
triggers this job (run.invoker), so the web service stays nearly read-only.
"""
import os
import json

from google.cloud import bigquery, storage
import google.auth
from google.auth.transport.requests import AuthorizedSession

import definitions_seed as seeder

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"
BUCKET = "bidbrain-analytics-status-dash"

REQUIRED_KEYS = ("client", "dataset", "_seed_spec")


def _bucket():
    return storage.Client(project=PROJECT).bucket(BUCKET)


def _read_json(obj):
    blob = _bucket().blob(obj)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_bytes())


def _write_json(obj, doc):
    blob = _bucket().blob(obj)
    blob.cache_control = "no-store"
    blob.upload_from_string(json.dumps(doc, indent=2), content_type="application/json")


def _validate(defs):
    """Structural validation of a staged definitions doc (no GCP). Raises ValueError on a problem."""
    for k in REQUIRED_KEYS:
        if k not in defs:
            raise ValueError(f"definitions missing required key '{k}'")
    spec = defs["_seed_spec"]
    if not isinstance(spec, list) or not spec:
        raise ValueError("_seed_spec must be a non-empty list")
    for e in spec:
        for f in ("table", "column", "path"):
            if f not in e:
                raise ValueError(f"_seed_spec entry missing '{f}': {e}")
        seeder.resolve_path(defs, e["path"])   # raises if the path can't resolve


def run_job(job):
    """RUN an existing Cloud Run job with FORCE_REBUILD=1, via the Run Admin API v2 :run endpoint.
    We only RUN it (no deploy/update) so this needs run.invoker, NOT actAs. Returns immediately —
    the export runs in the background and the dashboard refreshes within a couple of minutes."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sess = AuthorizedSession(creds)
    url = f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{LOC}/jobs/{job}:run"
    body = {"overrides": {"containerOverrides": [
        {"env": [{"name": "FORCE_REBUILD", "value": "1"}]}]}}
    r = sess.post(url, json=body, timeout=60)
    r.raise_for_status()
    print(f"  triggered {job} (FORCE_REBUILD=1)")


def main():
    client = os.environ.get("DEPLOY_CLIENT")
    if not client:
        raise SystemExit("DEPLOY_CLIENT env var is required (the client key to deploy).")
    print(f"status-deploy: client={client}")

    staged = _read_json(f"definitions/{client}.staged.json")
    if staged is None:
        raise SystemExit(f"no staged definitions at definitions/{client}.staged.json")
    _validate(staged)
    print(f"  validated staged definitions (last_edited_by={staged.get('last_edited_by')!r})")

    live = _read_json(f"definitions/{client}.json")   # kept for rollback
    bq = bigquery.Client(project=PROJECT)

    # 1) Seed the client_<c>.seed_* tables from the staged doc.
    seeder.seed_from_definitions(bq, staged)

    # 2) Smoke-check the client's views (they read the seed tables live).
    smoke_views = staged.get("_smoke_views", [])
    try:
        for v in smoke_views:
            n = list(bq.query(f"SELECT COUNT(*) AS n FROM `{PROJECT}.{v}`", location=LOC).result())[0]["n"]
            print(f"  smoke OK: {v} -> {n} rows")
    except Exception as e:   # noqa: BLE001
        print(f"  SMOKE CHECK FAILED: {e}")
        if live is not None:
            print("  rolling back seed tables to the live definitions ...")
            seeder.seed_from_definitions(bq, live)
            print("  rollback complete; nothing promoted or rebuilt.")
        raise SystemExit("smoke check failed — aborted (see rollback above).")

    # 3) Promote staged -> live, then rebuild the client dashboard + the status checks.
    _write_json(f"definitions/{client}.json", staged)
    _bucket().blob(f"definitions/{client}.staged.json").delete()
    print(f"  promoted staged -> definitions/{client}.json")

    run_job(f"{client}-export")
    run_job("status-export")
    print("status-deploy: DONE (exports running in the background; dashboards refresh shortly).")


if __name__ == "__main__":
    main()
