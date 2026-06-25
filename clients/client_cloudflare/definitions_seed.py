r"""Materialise a client's definitions.json into BigQuery seed_* tables.

This is the CLIENT side of the "single source of truth" mechanism (see definitions.json).
It reads the definitions doc (repo file locally, or the LIVE gs:// copy when run by the
status-deploy job) and WRITE_TRUNCATEs one tiny one-column table per `_seed_spec` entry.
The client's BigQuery VIEWS (sql/10, sql/14) read these seed tables LIVE, so reloading a
seed table changes what the dashboard reports on the next export run — no view re-apply,
no image rebuild.

GENERIC / data-driven: the loader logic is client-agnostic — each client's definitions.json
declares its own `_seed_spec`, so the SAME code seeds any client (the status-deploy job
vendors a copy of this file). Mirrors the load_seeds.py convention (WRITE_TRUNCATE, drop a
pre-existing view of the destination name first).

Run (local, repo seed copy):
    .\.venv\Scripts\python.exe clients\client_cloudflare\definitions_seed.py
Run against the live GCS copy:
    .\.venv\Scripts\python.exe clients\client_cloudflare\definitions_seed.py --source gs://bidbrain-analytics-status-dash/definitions/cloudflare.json
"""
import os
import sys
import json

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

# Default to this client's repo definitions file (the version-controlled seed copy).
_HERE = os.path.dirname(__file__)
DEFAULT_SOURCE = os.path.join(_HERE, "definitions.json")


def read_definitions(source):
    """Load a definitions doc from a local path or a gs:// URI -> dict."""
    if source.startswith("gs://"):
        from google.cloud import storage
        bucket, _, obj = source[len("gs://"):].partition("/")
        blob = storage.Client(project=PROJECT).bucket(bucket).blob(obj)
        return json.loads(blob.download_as_bytes())
    with open(source, encoding="utf-8") as f:
        return json.load(f)


def resolve_path(defs, path):
    """Resolve a tiny path expression against the definitions dict -> a flat list of scalars.

    Supports dotted keys and ONE list-of-objects hop via '[]':
      'segments.RIG.campaign_ids'  -> defs['segments']['RIG']['campaign_ids']  (already a list)
      'cs_campaigns[].id'          -> [c['id'] for c in defs['cs_campaigns']]
    """
    tokens = path.split(".")
    cur = defs
    for i, tok in enumerate(tokens):
        if tok.endswith("[]"):
            lst = cur[tok[:-2]]
            rest = tokens[i + 1:]
            out = []
            for item in lst:
                v = item
                for r in rest:
                    v = v[r]
                out.append(v)
            return out
        cur = cur[tok]
    if not isinstance(cur, list):
        raise ValueError(f"path '{path}' did not resolve to a list (got {type(cur).__name__})")
    return cur


def _ensure_not_view(bq, ref):
    """Drop `ref` if it currently exists as a VIEW — a load job can't overwrite a view.
    No-op once it's a table (or absent). Mirrors client_schneider/load_seeds.py."""
    from google.api_core.exceptions import NotFound
    try:
        t = bq.get_table(ref)
    except NotFound:
        return
    if t.table_type == "VIEW":
        bq.delete_table(ref)
        print(f"dropped pre-existing VIEW {ref} (migrating view -> table)")


def seed_from_definitions(bq, defs, dataset=None):
    """WRITE_TRUNCATE every seed_* table declared in defs['_seed_spec']. Returns a summary
    list of (table, row_count) for logging / the deploy audit."""
    dataset = dataset or defs["dataset"]
    spec = defs.get("_seed_spec", [])
    summary = []
    for entry in spec:
        table, column, path = entry["table"], entry["column"], entry["path"]
        values = [str(v) for v in resolve_path(defs, path) if v is not None]
        ref = f"{PROJECT}.{dataset}.{table}"
        _ensure_not_view(bq, ref)
        schema = [bigquery.SchemaField(column, "STRING")]
        if values:
            cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)
            rows = [{column: v} for v in values]
            bq.load_table_from_json(rows, ref, job_config=cfg, location=LOC).result()
        else:
            # An empty list still needs the table to EXIST (empty) so the views resolve.
            bq.query(f"CREATE OR REPLACE TABLE `{ref}` (`{column}` STRING)",
                     location=LOC).result()
        print(f"seeded {len(values):>3} row(s) -> {ref}")
        summary.append((table, len(values)))
    return summary


def main():
    source = DEFAULT_SOURCE
    argv = sys.argv[1:]
    if "--source" in argv:
        source = argv[argv.index("--source") + 1]
    defs = read_definitions(source)
    bq = bigquery.Client(project=PROJECT)
    print(f"seeding {defs.get('client')} definitions from {source}")
    seed_from_definitions(bq, defs)
    print("definitions seed complete.")


if __name__ == "__main__":
    main()
