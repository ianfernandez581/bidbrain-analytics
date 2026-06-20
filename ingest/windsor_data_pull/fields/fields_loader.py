"""
Windsor FIELD CATALOGUE loader -> raw_windsor.windsor_fields.

Fetches the full Windsor.ai blended-connector field reference
    https://connectors.windsor.ai/all/fields
(the JSON that the public https://windsor.ai/data-field/all/ page renders) and UPSERTS
it into BigQuery so we keep a queryable, daily-refreshed catalogue of EVERY field Windsor
exposes and WHICH connectors each is available in. ~37.8k fields at build time.

The endpoint is a CATALOGUE, not account data -> it is PUBLIC, so no api_key is needed.

Design mirrors the other windsor loaders (stage NDJSON through the shared staging bucket,
then MERGE), but the grain is a slowly-changing reference table, not daily metrics:

  1. GET the field list (capped-backoff retries on transient errors).
  2. Stage as NDJSON in gs://bidbrain-analytics-staging, load into a staging table.
  3. MERGE on `id` into raw_windsor.windsor_fields:
       - matched   -> refresh name/description/type/connectors, bump last_seen = today
       - unmatched -> INSERT with first_seen = last_seen = today   (== a NEW field)
     We never DELETE: a field Windsor drops just stops advancing last_seen.
  4. Report how many fields are NEW today (first_seen = CURRENT_DATE()).

Idempotent (MERGE on id). No date arguments. Run:
    python windsor_data_pull/fields/fields_loader.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

import requests
from google.cloud import bigquery, storage

PROJECT = "bidbrain-analytics"
LOCATION = "australia-southeast1"
DATASET = "raw_windsor"
TABLE = "windsor_fields"
STAGING_TABLE = "_stg_windsor_fields"
STAGING_BUCKET = "bidbrain-analytics-staging"
STAGING_PREFIX = "windsor_fields"

FIELDS_URL = "https://connectors.windsor.ai/all/fields"
SOURCE_TAG = "windsor.all/fields"

# ---- staging schema: only the fetched columns; first/last_seen are set in the MERGE ----
STAGING_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("type", "STRING"),
    bigquery.SchemaField("available_in_connectors", "STRING", mode="REPEATED"),
    bigquery.SchemaField("n_connectors", "INT64"),
    bigquery.SchemaField("raw_row", "JSON"),
]


def fetch_fields(retries=5):
    """GET the catalogue with capped-backoff retries on transient errors, fail-fast on 4xx."""
    backoff = 5
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(FIELDS_URL, timeout=300)
        except requests.exceptions.RequestException as e:
            if attempt == retries:
                raise
            print(f"  fetch attempt {attempt} failed ({type(e).__name__}): {e} -- retry in {backoff}s")
            time.sleep(backoff); backoff = min(backoff * 2, 120); continue
        if r.status_code == 200:
            return r.json()
        if 400 <= r.status_code < 500 and r.status_code != 429:
            raise RuntimeError(f"Windsor /all/fields permanent error HTTP {r.status_code}: {r.text[:400]}")
        if attempt == retries:
            raise RuntimeError(f"Windsor /all/fields HTTP {r.status_code} after {retries} tries: {r.text[:400]}")
        print(f"  HTTP {r.status_code} attempt {attempt} -- retry in {backoff}s")
        time.sleep(backoff); backoff = min(backoff * 2, 120)


def to_staging_row(f):
    connectors = f.get("available_in_connectors") or []
    if not isinstance(connectors, list):
        connectors = []
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "description": f.get("description"),
        "type": f.get("type"),
        "available_in_connectors": connectors,
        "n_connectors": len(connectors),
        "raw_row": json.dumps(f, ensure_ascii=False),
    }


def main():
    print("=" * 70)
    print("Windsor field-catalogue loader -> raw_windsor.windsor_fields")
    print(f"  source: {FIELDS_URL}")
    print("=" * 70)

    fields = fetch_fields()
    rows = [to_staging_row(f) for f in fields if f.get("id")]
    print(f"fetched {len(fields)} fields ({len(rows)} with an id)")
    if not rows:
        print("No fields returned -- aborting without touching BigQuery.")
        sys.exit(1)

    bq = bigquery.Client(project=PROJECT, location=LOCATION)
    gcs = storage.Client(project=PROJECT)

    # 1. write NDJSON locally
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False, encoding="utf-8")
    try:
        for r in rows:
            tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.close()

        # 2. upload to the shared staging bucket
        blob_name = f"{STAGING_PREFIX}/staging-{ts}.ndjson"
        blob = gcs.bucket(STAGING_BUCKET).blob(blob_name)
        blob.upload_from_filename(tmp.name, content_type="application/x-ndjson")
        gcs_uri = f"gs://{STAGING_BUCKET}/{blob_name}"
        print(f"uploaded {len(rows)} rows -> {gcs_uri}")
    finally:
        os.unlink(tmp.name)

    # 3. load -> staging table (truncate each run)
    stg_id = f"{PROJECT}.{DATASET}.{STAGING_TABLE}"
    load_cfg = bigquery.LoadJobConfig(
        schema=STAGING_SCHEMA,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    bq.load_table_from_uri(gcs_uri, stg_id, job_config=load_cfg).result()
    print(f"loaded staging table {stg_id}")

    # 4. MERGE on id (first_seen set once on insert; last_seen bumped every run)
    tgt = f"{PROJECT}.{DATASET}.{TABLE}"
    merge_sql = f"""
    MERGE `{tgt}` T
    USING `{stg_id}` S
    ON T.id = S.id
    WHEN MATCHED THEN UPDATE SET
        name = S.name,
        description = S.description,
        type = S.type,
        available_in_connectors = S.available_in_connectors,
        n_connectors = S.n_connectors,
        raw_row = S.raw_row,
        last_seen = CURRENT_DATE(),
        snapshot_date = CURRENT_DATE(),
        ingested_at = CURRENT_TIMESTAMP(),
        source = '{SOURCE_TAG}'
    WHEN NOT MATCHED THEN INSERT (
        id, name, description, type, available_in_connectors, n_connectors,
        first_seen, last_seen, snapshot_date, ingested_at, source, raw_row
    ) VALUES (
        S.id, S.name, S.description, S.type, S.available_in_connectors, S.n_connectors,
        CURRENT_DATE(), CURRENT_DATE(), CURRENT_DATE(), CURRENT_TIMESTAMP(), '{SOURCE_TAG}', S.raw_row
    )
    """
    bq.query(merge_sql).result()
    print(f"merged into {tgt}")

    # drop the staging table (keep the dataset tidy)
    bq.delete_table(stg_id, not_found_ok=True)

    # 5. report new / dropped
    summary = list(bq.query(f"""
        SELECT
          COUNTIF(first_seen = CURRENT_DATE()) AS new_today,
          COUNTIF(last_seen  < CURRENT_DATE()) AS gone,
          COUNT(*) AS total
        FROM `{tgt}`
    """).result())[0]
    print(f"catalogue: {summary.total} fields total | {summary.new_today} new today | "
          f"{summary.gone} no longer present")

    if summary.new_today:
        new_rows = bq.query(f"""
            SELECT id, name, type, n_connectors
            FROM `{tgt}` WHERE first_seen = CURRENT_DATE()
            ORDER BY id LIMIT 50
        """).result()
        print("  NEW fields today (first 50):")
        for r in new_rows:
            print(f"    + {r.id:<45} [{r.type}] in {r.n_connectors} connectors  ({r.name})")

    print("DONE.")


if __name__ == "__main__":
    main()
