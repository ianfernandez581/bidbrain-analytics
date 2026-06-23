r"""Generic definitions.json -> BigQuery seed_* loader (VENDORED).

Identical to clients/client_<c>/definitions_seed.py (kept in sync, like freshness.py / sf_connect
are vendored per job folder — Docker build contexts are per-folder, so we can't import across them).
The status-deploy worker imports `seed_from_definitions` + `resolve_path` from here.

GENERIC / data-driven: each client's definitions.json declares its own `_seed_spec`, so the SAME
code seeds any client. Reads the doc (gs:// or local), WRITE_TRUNCATEs one tiny one-column table
per `_seed_spec` entry; the client's BigQuery views read those seed tables live.
"""
import os
import sys
import json

from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC = "australia-southeast1"

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
    """Drop `ref` if it currently exists as a VIEW — a load job can't overwrite a view."""
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
    summary = []
    for entry in defs.get("_seed_spec", []):
        table, column, path = entry["table"], entry["column"], entry["path"]
        values = [str(v) for v in resolve_path(defs, path) if v is not None]
        ref = f"{PROJECT}.{dataset}.{table}"
        _ensure_not_view(bq, ref)
        schema = [bigquery.SchemaField(column, "STRING")]
        if values:
            cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=schema)
            bq.load_table_from_json([{column: v} for v in values], ref,
                                    job_config=cfg, location=LOC).result()
        else:
            bq.query(f"CREATE OR REPLACE TABLE `{ref}` (`{column}` STRING)", location=LOC).result()
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
