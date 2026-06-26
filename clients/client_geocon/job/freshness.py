"""Freshness gate -- the shared self-gating helper, vendored per job folder.

Every export job runs on a frequent (*/N) Cloud Scheduler tick but only does its
expensive rebuild + upload when the upstream it reads has ACTUALLY changed. This
module is the gate: it probes upstream freshness cheaply, compares against a
stored watermark, and answers is_stale().

Two probe sources, depending on what the job reads (see the repo "Freshness
contract" in CLAUDE.md):

  * Snowflake-direct jobs (e.g. client_cloudflare, snowflake_data_pull) ->
    probe_snowflake_last_altered(): reads INFORMATION_SCHEMA.TABLES.LAST_ALTERED.
    METADATA-ONLY -- no warehouse credits, never resumes APAC_IN_WH. Key-pair
    connect doesn't resume it either, so a "nothing changed" tick is ~free.

  * BigQuery-reading jobs (every other client, reading raw_snowflake / raw_windsor
    / raw_ga4 / raw_google_ads / raw_neto mirrors) -> probe_bq_last_modified():
    reads __TABLES__.last_modified_time. A plain metadata read.

Never watermark a VIEW -- a view's LAST_ALTERED only moves on DDL. Watermark the
base tables / mirror tables the views read.

The watermark is a tiny JSON sidecar in the client's own GCS bucket
("_freshness.json"); snowflake_data_pull instead keeps a per-table BQ _sync_state.

NO new pip dependencies and NO heavy imports at module top: google-cloud-storage
is imported lazily inside the watermark helpers, and the BigQuery/Snowflake
clients are passed in by the caller. Keep pandas/pyarrow/bigquery out of the
no-op tick's import path so an idle tick stays a light, fast container.
"""
import json
import datetime

BQ_LOCATION = "australia-southeast1"  # the project's single region (see CLAUDE.md)


def _to_utc(dt):
    """Normalise a Snowflake TIMESTAMP_LTZ / BQ TIMESTAMP (or naive) to second-precision UTC.

    Truncating sub-second precision keeps the round-trip consistent: the watermark
    is stored to whole seconds, so probe values must compare at the same
    granularity or every tick would look "newer" than the stored value.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).replace(microsecond=0)


def _iso(dt):
    """UTC datetime -> 'YYYY-MM-DDTHH:MM:SSZ' (the watermark's on-disk form)."""
    dt = _to_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _parse_iso(s):
    """Watermark ISO string -> second-precision UTC datetime (None-safe)."""
    if not s:
        return None
    return _to_utc(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")))


def probe_snowflake_last_altered(cn, table_names):
    """Return {bare_table_name: LAST_ALTERED (UTC datetime)} for the given PUBLIC tables.

    One metadata-only round trip against APAC_ALL_PLATFORM.INFORMATION_SCHEMA.TABLES;
    does NOT resume the warehouse. Table names carry embedded spaces, so they're
    passed as bind parameters rather than quoted by hand. Only existing tables come
    back, so absent names are simply omitted.
    """
    if not table_names:
        return {}
    placeholders = ", ".join(["%s"] * len(table_names))
    sql = (
        "SELECT TABLE_NAME, LAST_ALTERED "
        "FROM APAC_ALL_PLATFORM.INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = 'PUBLIC' "
        f"AND TABLE_NAME IN ({placeholders})"
    )
    cur = cn.cursor()
    try:
        cur.execute(sql, tuple(table_names))
        return {name: _to_utc(last_altered) for name, last_altered in cur.fetchall()}
    finally:
        cur.close()


def probe_bq_last_modified(bq, tables, location=BQ_LOCATION):
    """Return {"dataset.table": last_modified (UTC datetime)} for the given BQ tables.

    `tables` is an iterable of "dataset.table" strings in the job's own project
    (e.g. "raw_snowflake.tradedesk_apac_all", "raw_windsor.perf_meta"). Reading
    `__TABLES__.last_modified_time` is metadata-only and needs only existing BQ
    read access. Tables are grouped by dataset (one query each) and keyed back as
    "dataset.table" so multi-dataset clients never collide on a bare table id.
    """
    by_ds = {}
    for t in tables:
        ds, _, tid = t.partition(".")
        by_ds.setdefault(ds, []).append(tid)
    out = {}
    for ds, ids in by_ds.items():
        in_list = ", ".join("'" + i.replace("'", "''") + "'" for i in ids)
        sql = (
            "SELECT table_id, TIMESTAMP_MILLIS(last_modified_time) AS lm "
            f"FROM `{bq.project}.{ds}.__TABLES__` "
            f"WHERE table_id IN ({in_list})"
        )
        for row in bq.query(sql, location=location).result():
            out[f"{ds}.{row['table_id']}"] = _to_utc(row["lm"])
    return out


def read_watermark(bucket, key):
    """Read the JSON watermark sidecar from GCS -> {name: iso_string}.

    Missing object (cold start) -> {}. Uses google-cloud-storage (lazy import);
    the job's runtime SA already has objectAdmin on its bucket, so no new grant.
    """
    from google.cloud import storage
    blob = storage.Client().bucket(bucket).blob(key)
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text())


def write_watermark(bucket, key, observed):
    """Persist {name: iso_utc_string} as the JSON watermark sidecar in GCS.

    `observed` is a probe dict (datetimes); values are stored as ISO strings.
    Idempotent: last-write-wins, no lock needed at a */10 cadence.
    """
    from google.cloud import storage
    payload = {name: _iso(dt) for name, dt in observed.items()}
    storage.Client().bucket(bucket).blob(key).upload_from_string(
        json.dumps(payload, indent=2, sort_keys=True),
        content_type="application/json")


def is_stale(observed, watermark):
    """True if any observed timestamp is newer than the stored watermark, OR a probed
    key is absent from the watermark (cold start / new table => True).

    An empty `observed` (probe found nothing / failed) yields False: don't burn a
    rebuild on a broken probe -- it retries next tick.
    """
    for name, dt in observed.items():
        if dt is None:
            continue
        prev = _parse_iso(watermark.get(name))
        if prev is None or dt > prev:
            return True
    return False
