r"""
client_cloudflare/convert_line_export.py -- turn a MANUAL LINE Ad Manager report
export into data/line_cf.csv (the seed_line_cf source).

WHY THIS EXISTS
---------------
LINE is the one Cloudflare channel with no API/Windsor connector -- it is a manual
CSV download from https://admanager.line.biz/ (Performance report, aggregation
interval = Daily). The LINE Ads account is also migrating to LY Ads, so the old
Snowflake relay (V_STG_LINE_CF -> pull_static.py) is being retired; this script is
the new path: LINE daily export -> data/line_cf.csv directly. Then seed_static.py
loads it to BigQuery and the export job rebuilds (FORCE_REBUILD=1).

The LINE daily report columns we use (matched BY NAME, header is English here):
    Day, Ad name, Impressions, Clicks, Cost   (Cost is JPY)
seed_line_cf wants, IN THIS ORDER:
    DAY, AD_NAME, IMPRESSIONS, CLICKS, COST, VIDEO_STARTS, VIDEO_100_WATCHED
These ads are IMAGE (1200x627), no video -> VIDEO_STARTS/VIDEO_100_WATCHED = 0
(the old seed had them 0 too). Rows are summed to one per (DAY, AD_NAME) -- the
same ad name runs under multiple ad groups, and the model rolls up to daily totals.

Run:  .\.venv\Scripts\python.exe clients\client_cloudflare\convert_line_export.py "<path-to-LINE-export.csv>"
      (omit the path to auto-pick the newest LINE*.csv in ~/Downloads)
"""
import os
import sys
import glob
import pandas as pd

DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
OUT_PATH  = os.path.join(DATA_DIR, "line_cf.csv")
# Set to a YYYY-MM-DD to clamp; None keeps every delivery day. The old seed kept
# everything (its first delivery day was 2026-04-06), so default to no clamp.
START_DATE = None

OUT_COLS = ["DAY", "AD_NAME", "IMPRESSIONS", "CLICKS", "COST",
            "VIDEO_STARTS", "VIDEO_100_WATCHED"]


def _find_export():
    if len(sys.argv) > 1:
        return sys.argv[1]
    dl = os.path.join(os.path.expanduser("~"), "Downloads")
    hits = sorted(glob.glob(os.path.join(dl, "LINE*.csv")), key=os.path.getmtime)
    if not hits:
        sys.exit("No LINE*.csv found in ~/Downloads -- pass the path explicitly.")
    return hits[-1]


def main():
    src = _find_export()
    print(f"reading  {src}")
    # utf-8-sig drops the BOM the LINE export ships with.
    df = pd.read_csv(src, encoding="utf-8-sig", dtype=str)

    # LINE -> seed columns (by header name).
    out = pd.DataFrame({
        "DAY":         pd.to_datetime(df["Day"], format="%Y/%m/%d").dt.strftime("%Y-%m-%d"),
        "AD_NAME":     df["Ad name"].str.strip(),
        "IMPRESSIONS": pd.to_numeric(df["Impressions"], errors="coerce").fillna(0).astype(int),
        "CLICKS":      pd.to_numeric(df["Clicks"],      errors="coerce").fillna(0).astype(int),
        "COST":        pd.to_numeric(df["Cost"],        errors="coerce").fillna(0).round().astype(int),
    })

    if START_DATE:
        before = len(out)
        out = out[out["DAY"] >= START_DATE]
        print(f"clamp    >= {START_DATE}  (dropped {before - len(out)} pre-launch rows)")

    # one row per (day, ad) -- sum across ad groups; model groups by day anyway.
    out = (out.groupby(["DAY", "AD_NAME"], as_index=False)
              .agg(IMPRESSIONS=("IMPRESSIONS", "sum"),
                   CLICKS=("CLICKS", "sum"),
                   COST=("COST", "sum")))
    out["VIDEO_STARTS"] = 0
    out["VIDEO_100_WATCHED"] = 0
    out = out[OUT_COLS].sort_values(["DAY", "AD_NAME"])

    os.makedirs(DATA_DIR, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)
    print(f"wrote    {len(out)} rows -> {OUT_PATH}")
    print(f"range    {out['DAY'].min()} .. {out['DAY'].max()}")
    print(f"totals   imps={out['IMPRESSIONS'].sum():,}  clicks={out['CLICKS'].sum():,}  "
          f"cost(JPY)={out['COST'].sum():,}  ~USD@155={out['COST'].sum()/155:,.0f}")


if __name__ == "__main__":
    main()
