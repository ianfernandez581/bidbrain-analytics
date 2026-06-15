r"""
client_mongodb/seed_pixel.py — load a Trade Desk "Pixel - Overall Performance"
CSV export into BigQuery as the static source for the dashboard's
Content-Engagement section.

WHY this is a seed and not part of the shared Snowflake pull: the raw_snowflake
mirror (raw_snowflake.tradedesk_apac_all) only carries a single BLENDED conversion
count per row. This TTD report breaks conversions out BY UNIVERSAL-PIXEL EVENT
(which content landing page people reached) and adds Device / Ad-Environment /
Creative-size cuts the mirror throws away. None of that exists upstream, so it
arrives as a hand-pulled CSV and is seeded here — same idea as
client_cloudflare/seed_static.py, but the source is a local CSV, not Snowflake.

It writes TWO tidy tables into client_mongodb (WRITE_TRUNCATE — re-running fully
replaces them):
  * seed_tradedesk_pixel         — one row per CSV row: dims + delivery (imps/cost/clicks)
  * seed_tradedesk_pixel_assets  — pixel conversions melted long (one row per
                                   non-zero pixel event), so the views GROUP BY cleanly.

The SQL views (sql/11_pixel_assets, 12_pixel_dims, 13_pixel_summary) read these,
and the export job folds them into mongodb.json under the "pixel" key. The job's
freshness gate watches seed_tradedesk_pixel's last_modified, so re-running this
loader makes the next */10 tick rebuild automatically (no FORCE_REBUILD needed).

DROP LOCATION: put the export in client_mongodb/data/ (gitignored). By default the
newest "*Overall Performance*.csv" there is used; override with $PIXEL_CSV.

Run:  .\.venv\Scripts\python.exe clients\client_mongodb\seed_pixel.py
"""
import os
import glob
import pandas as pd
from google.cloud import bigquery

PROJECT = "bidbrain-analytics"
LOC     = "australia-southeast1"
DATASET = "client_mongodb"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

TBL_MAIN   = "seed_tradedesk_pixel"
TBL_ASSETS = "seed_tradedesk_pixel_assets"

# The seven Universal Pixel events in the export, as
#   (asset_key, full CSV column prefix, human label).
# Each prefix has three measure columns appended in the CSV:
#   " - Total Click + View Conversions", " - Click Conversion", " - View Through Conversion".
# 'default' is the catch-all site pixel (mostly inflated view-through site visits);
# the other six are specific content landing pages. The views split them apart.
PIXELS = [
    ("gartner_mq",         "MDB_UPM_LPView_Gartner_MQ_Leader - hb1953e - IdentityAlliance", "Gartner MQ Leader"),
    ("ai_readiness",       "MDB_UPM_LPView_AI_Readiness - mql95t9 - IdentityAlliance",       "AI Readiness"),
    ("ai_datasilos",       "MDB_UPM_LPView_AI_DataSilos - g1fgext - IdentityAlliance",       "AI Data Silos"),
    ("idc_winningai",      "MDB_UPM_LPView_IDC_WinningAI - yomwmoh - IdentityAlliance",      "IDC Winning AI"),
    ("payments_modernize", "MDB_UPM_LPView_Payments_Modernize - x8n548g - IdentityAlliance", "Payments Modernize"),
    ("payments_instant",   "MDB_UPM_LPView_Payments_Instant - weyrfy7 - IdentityAlliance",   "Payments Instant"),
    ("default",            "MongoDB Universal Pixel - Default - joksmyz - IdentityAlliance", "All pages (Default)"),
]


def find_csv():
    override = os.environ.get("PIXEL_CSV")
    if override:
        if not os.path.exists(override):
            raise SystemExit(f"$PIXEL_CSV not found: {override}")
        return override
    hits = glob.glob(os.path.join(DATA_DIR, "*Overall Performance*.csv"))
    if not hits:
        raise SystemExit(
            f"No '*Overall Performance*.csv' in {os.path.abspath(DATA_DIR)} — "
            f"drop the Trade Desk pixel export there (or set $PIXEL_CSV).")
    return max(hits, key=os.path.getmtime)   # newest


def load(bq, df, table):
    ref = f"{PROJECT}.{DATASET}.{table}"
    cfg = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    bq.load_table_from_dataframe(df, ref, job_config=cfg, location=LOC).result()
    print(f"loaded {len(df):>7,} rows  ->  {ref}")


def main():
    path = find_csv()
    print(f"reading {path}")
    # thousands=',' so quoted figures like "1,411" parse as numbers, not strings.
    raw = pd.read_csv(path, thousands=",")

    # ---- table 1: row-level delivery + dimensions ----------------------------
    # PROGRAMME/MARKET/STRATEGY parsed from the campaign / ad-group names with the
    # SAME split offsets as sql/01_stg_tradedesk.sql, so the two stay consistent:
    #   campaign  MONGODB_2026-Q2_<PROGRAMME>_APJ_DEMAND-GENERATION_<MARKET>
    #   ad group  ..._<MARKET>_<STRATEGY>
    camp = raw["Campaign"].str.split("_")
    grp  = raw["Ad Group"].str.split("_")
    main_df = pd.DataFrame({
        "DAY":            pd.to_datetime(raw["Date"], format="%m/%d/%Y").dt.date,
        "CAMPAIGN":       raw["Campaign"],
        "PROGRAMME":      camp.str[2],
        "MARKET":         camp.str[5],
        "AD_GROUP":       raw["Ad Group"],
        "STRATEGY":       grp.str[6],
        "AD_FORMAT":      raw["Ad Format"],
        "MEDIA_TYPE":     raw["Media Type"],
        "BROWSER":        raw["Browser"],
        "DEVICE_TYPE":    raw["Device Type"],
        "AD_ENVIRONMENT": raw["Ad Environment"],
        "CURRENCY":       raw["Advertiser Currency Code"],
        "IMPRESSIONS":    raw["Impressions"].fillna(0).astype("int64"),
        "COST_USD":       raw["Advertiser Cost (Adv Currency)"].fillna(0.0).astype(float),
        "CLICKS":         raw["Clicks"].fillna(0).astype("int64"),
        "ALL_CONV":       raw["All Last Click + View Conversions"].fillna(0).astype(float),
    })

    # ---- table 2: pixel conversions melted long (drop all-zero rows) ---------
    base = main_df[["DAY", "CAMPAIGN", "PROGRAMME", "MARKET"]]
    frames = []
    for key, prefix, label in PIXELS:
        sub = base.copy()
        sub["ASSET_KEY"]  = key
        sub["ASSET"]      = label
        sub["CLICK_CONV"] = raw[f"{prefix} - Click Conversion"].fillna(0).astype("int64")
        sub["VIEW_CONV"]  = raw[f"{prefix} - View Through Conversion"].fillna(0).astype("int64")
        sub["TOTAL_CONV"] = raw[f"{prefix} - Total Click + View Conversions"].fillna(0).astype("int64")
        frames.append(sub)
    assets = pd.concat(frames, ignore_index=True)
    assets = assets[(assets.TOTAL_CONV != 0) | (assets.CLICK_CONV != 0) | (assets.VIEW_CONV != 0)]

    bq = bigquery.Client(project=PROJECT)
    load(bq, main_df, TBL_MAIN)
    load(bq, assets,  TBL_ASSETS)
    print(f"done. window {main_df.DAY.min()} -> {main_df.DAY.max()} | "
          f"{main_df.IMPRESSIONS.sum():,} imps | ${main_df.COST_USD.sum():,.0f} | "
          f"{int(assets.loc[assets.ASSET_KEY!='default','TOTAL_CONV'].sum()):,} content LP views")


if __name__ == "__main__":
    main()
