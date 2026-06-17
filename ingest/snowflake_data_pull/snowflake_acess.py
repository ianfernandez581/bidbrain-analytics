#!/usr/bin/env python3
"""sf_pull.py - ad-hoc, read-only Snowflake query harness for the APAC paid-media warehouse.

PURPOSE
-------
Gives a local agent (Claude Code / Cline in VS Code) - or you at the CLI - the ability to PULL
directly from the Snowflake source while reconstructing the MongoDB Trade Desk Universal-Pixel
section from live data instead of the manual seed CSV. Run it bare to get the MongoDB pixel
extract from the conversion table; pass --sql / --sql-file to run anything else.

This is a DEV / exploration tool. The eventual production path is unchanged - mirror the table
into raw_snowflake via ingest/snowflake_data_pull/, then a client_mongodb/sql/ view - but this
lets the agent see the real rows first and iterate against them.

SOURCE OF INTEREST (verified)
-----------------------------
  APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL-Conversion"   (one row per pixel fire)
  MongoDB pixels  ->  ADVERTISER_ID = '9c1w83i'   (== the MDB_* / "MongoDB ..." tracking-tag names)
  Coverage today  ->  MongoDB rows start 2026-06-01 (the table itself goes back to 2026-04-01).
  Click vs view-through is DERIVED: DISPLAY_CLICK_COUNT > 0 => click-attributed, else view-through.
  (There is no per-pixel media spend here, and no device / ad-environment / creative-size cut -
   those live only in the manual TTD "Pixel - Overall Performance" CSV.)

AUTH (key-pair, matching ingest/snowflake_data_pull/)
-----------------------------------------------------
Connection settings come from env vars; the private key from a file. NOTHING secret is committed.
If ingest/snowflake_data_pull/ already exposes a working connect helper, prefer pointing connect()
at that (see the note in connect()) so this can't drift from your real loader.

  SNOWFLAKE_USER                    (required)
  SNOWFLAKE_ROLE                    (optional)
  SNOWFLAKE_ACCOUNT                 default: zgkghoh-isa98947
  SNOWFLAKE_WAREHOUSE               default: APAC_IN_WH
  SNOWFLAKE_DATABASE                default: APAC_ALL_PLATFORM
  SNOWFLAKE_SCHEMA                  default: PUBLIC
  SNOWFLAKE_PRIVATE_KEY_PATH        default: <this file>/../../bidbrain-vault/snowflake_key.p8
                                    (i.e. assumes the script sits in clients/client_mongodb/;
                                     set this to your actual vault key filename / location)
  SNOWFLAKE_PRIVATE_KEY_PASSPHRASE  (optional - only if the key is encrypted)
  SNOWFLAKE_PASSWORD                (optional - if set, used INSTEAD of key-pair)

CREDIT NOTE: querying a real table RESUMES the warehouse (APAC_IN_WH) and costs credits - unlike
the metadata-only freshness probes in freshness.py. Keep exploratory pulls small; the default
query is a light aggregate.

INSTALL (if your venv doesn't already have it)
  pip install snowflake-connector-python      # pulls cryptography in as a dependency

RUN
  python sf_pull.py                            # MongoDB pixel extract, preview to stdout
  python sf_pull.py --sql 'SELECT 1'           # arbitrary query
  python sf_pull.py --sql-file myquery.sql     # query from a file
  python sf_pull.py --out pixel.csv            # full results -> CSV (for the agent to read)
  python sf_pull.py --json --out pixel.json    # full results -> JSON
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# --- defaults (every one overridable via the matching env var) ---------------
DEFAULTS = {
    "SNOWFLAKE_ACCOUNT": "zgkghoh-isa98947",
    "SNOWFLAKE_WAREHOUSE": "APAC_IN_WH",
    "SNOWFLAKE_DATABASE": "APAC_ALL_PLATFORM",
    "SNOWFLAKE_SCHEMA": "PUBLIC",
}
# Private-key default location, relative to this script. Two levels up + bidbrain-vault matches
# the script living at clients/client_mongodb/sf_pull.py. Override with SNOWFLAKE_PRIVATE_KEY_PATH
# (the vault key filename is a guess - point it at your real .p8).
DEFAULT_KEY_PATH = Path(__file__).resolve().parent / ".." / ".." / "bidbrain-vault" / "snowflake_key.p8"

# Default pull: the MongoDB Universal-Pixel content-asset breakdown from the conversion table,
# with click-attributed vs view-through derived from DISPLAY_CLICK_COUNT. This is exactly the
# shape the pixel_assets / pixel_summary content split needs.
MONGODB_PIXEL_SQL = r"""
SELECT
    TRACKING_TAG_NAME,
    COUNT(*)                                       AS FIRES,
    COUNT(DISTINCT TDID)                           AS DISTINCT_USERS,
    COUNT_IF(DISPLAY_CLICK_COUNT > 0)              AS CLICK_CONV,
    COUNT_IF(COALESCE(DISPLAY_CLICK_COUNT, 0) = 0) AS VIEW_CONV,
    MIN(DAY)                                       AS FIRST_DAY,
    MAX(DAY)                                       AS LAST_DAY
FROM APAC_ALL_PLATFORM.PUBLIC."TradeDesk_APAC ALL-Conversion"
WHERE ADVERTISER_ID = '9c1w83i'
GROUP BY TRACKING_TAG_NAME
ORDER BY FIRES DESC
"""


def _cfg(name: str) -> str | None:
    return os.environ.get(name) or DEFAULTS.get(name)


def _load_private_key_der(path: Path, passphrase: str | None) -> bytes:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        path.read_bytes(),
        password=passphrase.encode() if passphrase else None,
        backend=default_backend(),
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def connect():
    """Open a Snowflake connection (key-pair by default; password if SNOWFLAKE_PASSWORD is set).

    If ingest/snowflake_data_pull/ already has a tested connect helper, replace this body with a
    call to it - this version is deliberately self-contained so the script runs standalone for the
    agent, but reusing your loader's connection avoids two places to keep in sync.
    """
    import snowflake.connector

    user = os.environ.get("SNOWFLAKE_USER")
    if not user:
        sys.exit("SNOWFLAKE_USER is required (set it in your env / .env file).")

    common = dict(
        account=_cfg("SNOWFLAKE_ACCOUNT"),
        user=user,
        warehouse=_cfg("SNOWFLAKE_WAREHOUSE"),
        database=_cfg("SNOWFLAKE_DATABASE"),
        schema=_cfg("SNOWFLAKE_SCHEMA"),
    )
    role = os.environ.get("SNOWFLAKE_ROLE")
    if role:
        common["role"] = role

    password = os.environ.get("SNOWFLAKE_PASSWORD")
    if password:
        return snowflake.connector.connect(password=password, **common)

    key_path = Path(os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", str(DEFAULT_KEY_PATH))).expanduser()
    if not key_path.exists():
        sys.exit(f"private key not found at {key_path}\n"
                 f"  set SNOWFLAKE_PRIVATE_KEY_PATH to your vault .p8, or set SNOWFLAKE_PASSWORD.")
    pkb = _load_private_key_der(key_path, os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"))
    return snowflake.connector.connect(private_key=pkb, **common)


def run_query(sql: str):
    """Execute SQL; return (columns, rows). Importable so the eventual loader can reuse it."""
    conn = connect()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql)
            cols = [c[0] for c in cur.description]
            return cols, cur.fetchall()
        finally:
            cur.close()
    finally:
        conn.close()


def _print_preview(cols, rows, limit: int) -> None:
    shown = rows[:limit]
    widths = [len(c) for c in cols]
    for r in shown:
        for i, v in enumerate(r):
            widths[i] = max(widths[i], len(str(v)))
    print("  ".join(c.ljust(widths[i]) for i, c in enumerate(cols)))
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for r in shown:
        print("  ".join(str(v).ljust(widths[i]) for i, v in enumerate(r)))
    extra = len(rows) - len(shown)
    if extra > 0:
        print(f"... (+{extra} more rows - use --out to dump everything)")


def _write_csv(path: Path, cols, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def _write_json(path: Path, cols, rows) -> None:
    payload = [
        {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, r)}
        for r in rows
    ]
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Ad-hoc read-only Snowflake pull (APAC paid-media warehouse).")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--sql", help="SQL to run (defaults to the MongoDB pixel extract).")
    src.add_argument("--sql-file", help="Path to a .sql file to run.")
    ap.add_argument("--out", help="Write FULL results to this path (CSV, or JSON with --json).")
    ap.add_argument("--json", action="store_true", help="With --out, write JSON instead of CSV.")
    ap.add_argument("--limit", type=int, default=50, help="Preview rows to print to stdout (default 50).")
    args = ap.parse_args()

    if args.sql_file:
        sql = Path(args.sql_file).read_text(encoding="utf-8")
    elif args.sql:
        sql = args.sql
    else:
        sql = MONGODB_PIXEL_SQL

    cols, rows = run_query(sql)
    print(f"\n{len(rows)} row(s).\n")
    _print_preview(cols, rows, args.limit)

    if args.out:
        out = Path(args.out)
        (_write_json if args.json else _write_csv)(out, cols, rows)
        print(f"\nwrote {out} ({len(rows)} rows).")


if __name__ == "__main__":
    main()