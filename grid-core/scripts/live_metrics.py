#!/usr/bin/env python
"""
live_metrics.py — pull live per-campaign metrics from BigQuery for The Grid.

The Grid's spend/impressions/clicks are supposed to be SCRAPED (live), while the
commercial columns (budgets, targets, margins, owners, dates) stay manually typed.
This module is the scraped half: it reads the same BigQuery layer that already
powers the client dashboards (so the grid matches the dashboards number-for-number)
and returns, per (advertiser, campaign, channel), the live spend/imps/clicks.

Two consumers:
  - build_grid_data.py overlays these onto the sheet-seeded DATA rows (the grid
    then shows BQ numbers instead of the stale manual ones).
  - reconcile() writes a sheet-vs-BQ comparison CSV so we can sign off each
    platform before trusting it (Trade Desk vs LinkedIn diverge today — see README).

Access: shells out to the `bq` CLI as ian@100.digital (ADC in the venv is a
different account), so no google-cloud-bigquery / ADC dependency is needed.

COVERAGE is intentionally explicit: only advertisers with a validated mapping in
CLIENTS below are scraped. Everything else stays on its sheet numbers and is
tagged 'sheet'. Add a client by adding a validated entry here — never guess a
join, or the grid shows wrong numbers.
"""
import csv
import io
import os
import subprocess
from pathlib import Path

PROJECT = "bidbrain-analytics"
ACCOUNT = "ian@100.digital"
REPO = Path(__file__).resolve().parents[2]

# platform enum (BQ) -> grid channel label. Shared across clients.
PLATFORM_TO_CHANNEL = {
    "tradedesk": "TradeDesk",
    "linkedin": "Linkedin",
    "google_ads": "Google Ads",
    "dv360": "DV360",
    "meta": "Meta",
    "reddit": "Reddit",
}

# Per-advertiser live-metrics source. Each entry is a validated join from the
# grid's (campaign, channel) rows to a BigQuery per-campaign spend view.
#   sql        : returns columns program, platform, spend, imps, clicks, last_date
#   program_to_campaign : BQ program key -> the grid's campaign label (exact match)
# Only advertisers listed here are scraped; add one only after reconciling it.
CLIENTS = {
    "Schneider": {
        "sql": """
            SELECT program, platform,
                   ROUND(SUM(spend_aud), 2) AS spend,
                   CAST(SUM(imps) AS INT64) AS imps,
                   CAST(SUM(clicks) AS INT64) AS clicks,
                   CAST(MAX(metric_date) AS STRING) AS last_date
            FROM `bidbrain-analytics.client_schneider.pm_delivery`
            GROUP BY 1, 2
        """,
        "program_to_campaign": {
            "water_env": "Water and Environment",
            "eba": "EBA",
            "airset": "Airset",
            "global_rebrand": "Advancing Energy T",
            "nel": "NEL",
        },
    },
}


def _bq_csv(sql):
    """Run a query via the bq CLI, return list[dict] (CSV parsed). Uses shell=True
    because on Windows `bq` is a .cmd wrapper; the SQL is collapsed to one line and
    contains no double quotes, so quoting is safe."""
    env = dict(os.environ, CLOUDSDK_CORE_ACCOUNT=ACCOUNT)
    one_line = " ".join(sql.split())
    assert '"' not in one_line, "SQL must not contain double quotes (shell quoting)"
    cmd = (f'bq --project_id={PROJECT} --format=csv query '
           f'--use_legacy_sql=false --max_rows=100000 "{one_line}"')
    out = subprocess.run(cmd, capture_output=True, text=True, env=env, shell=True)
    if out.returncode != 0:
        raise RuntimeError(f"bq query failed:\n{out.stderr.strip()[:800]}")
    return list(csv.DictReader(io.StringIO(out.stdout)))


def fetch(only=None):
    """Return {(advertiser, campaign, channel): {spend, imps, clicks, last_date}}.

    only: optional iterable of advertiser names to restrict the pull.
    """
    live = {}
    for adv, spec in CLIENTS.items():
        if only and adv not in only:
            continue
        rows = _bq_csv(spec["sql"])
        for r in rows:
            camp = spec["program_to_campaign"].get(r["program"])
            chan = PLATFORM_TO_CHANNEL.get(r["platform"])
            if not camp or not chan:
                continue          # program/platform not surfaced in the grid
            key = (adv, camp, chan)
            m = live.setdefault(key, {"spend": 0.0, "imps": 0, "clicks": 0, "last_date": None})
            m["spend"] += float(r["spend"] or 0)
            m["imps"] += int(r["imps"] or 0)
            m["clicks"] += int(r["clicks"] or 0)
            if r["last_date"] and (m["last_date"] is None or r["last_date"] > m["last_date"]):
                m["last_date"] = r["last_date"]
    return live


def overlay(rows, live):
    """Mutate grid rows in place: where a live metric exists, replace the scraped
    columns (impressions/clicks/mediaSpend) and the spend that drives pacing
    (clientSpent), and recompute budgetRemaining / pctSpent. Manual columns are
    untouched. Tags each row with metricsSource ('BQ' | 'sheet') + dataThrough.
    Returns the count of rows overlaid."""
    n = 0
    for c in rows:
        key = (c.get("advertiser"), c.get("campaign"), c.get("channel"))
        m = live.get(key)
        if not m:
            c["metricsSource"] = "sheet"
            continue
        c["impressions"] = float(m["imps"])
        c["clicks"] = float(m["clicks"])
        c["mediaSpend"] = round(m["spend"], 2)
        c["clientSpent"] = round(m["spend"], 2)     # interim: BQ spend drives delivery/pacing
        if c.get("totalBudget"):
            c["budgetRemaining"] = round(c["totalBudget"] - m["spend"], 2)
            c["pctSpent"] = round(m["spend"] / c["totalBudget"], 4) if c["totalBudget"] else None
        c["metricsSource"] = "BQ"
        c["dataThrough"] = m["last_date"]
        n += 1
    return n


def baseline_from(rows):
    """Snapshot the sheet's spend/impressions per key BEFORE overlay mutates them,
    so reconcile() can compare sheet vs BQ."""
    return {
        (r.get("advertiser"), r.get("campaign"), r.get("channel")): {
            "mediaSpend": r.get("mediaSpend"), "clientSpent": r.get("clientSpent"),
            "impressions": r.get("impressions"),
        }
        for r in rows
    }


def reconcile(baseline, live, out_path=None):
    """Write a sheet-vs-BQ comparison CSV (one row per grid campaign/channel that
    has a live number). Used to sign off each platform before trusting it."""
    out_path = Path(out_path) if out_path else (REPO / "grid-core" / "tmp" / "reconciliation.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["advertiser", "campaign", "channel", "sheet_mediaSpend", "sheet_clientSpent",
              "bq_spend", "spend_ratio_bq_over_sheetMedia", "sheet_impressions", "bq_impressions",
              "bq_through", "verdict"]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for (adv, camp, chan), m in sorted(live.items()):
            base = baseline.get((adv, camp, chan), {})
            sm = base.get("mediaSpend")
            ratio = round(m["spend"] / sm, 2) if sm else None
            verdict = "no-sheet-baseline"
            if ratio is not None:
                verdict = "match" if 0.9 <= ratio <= 1.1 else f"DIVERGES x{ratio}"
            w.writerow({
                "advertiser": adv, "campaign": camp, "channel": chan,
                "sheet_mediaSpend": sm, "sheet_clientSpent": base.get("clientSpent"),
                "bq_spend": round(m["spend"], 2), "spend_ratio_bq_over_sheetMedia": ratio,
                "sheet_impressions": base.get("impressions"), "bq_impressions": m["imps"],
                "bq_through": m["last_date"], "verdict": verdict,
            })
    return out_path


if __name__ == "__main__":
    live = fetch()
    print(f"fetched live metrics for {len(live)} (advertiser, campaign, channel) keys:")
    for k, m in sorted(live.items()):
        print(f"  {k[0]:<12} {k[1]:<24} {k[2]:<10} spend={m['spend']:>10.2f} imps={m['imps']:>9} through={m['last_date']}")
