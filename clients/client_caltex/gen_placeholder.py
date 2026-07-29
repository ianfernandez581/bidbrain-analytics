r"""Generate dash/placeholder.json — a Caltex-branded SAMPLE payload for the placeholder dashboard.

Emits a payload that matches EXACTLY the JSON contract job/main.py builds from BigQuery
(meta / flight / benchmarks / targets / rows[]) for the TRADE DESK model (advertiser 0lw3hp6,
mixed awareness + consideration display in QLD+WA), but every number is synthetic + deterministic.
The single tell is `meta.placeholder = true`, which dashboard.html renders behind a loud "sample
data" banner and which main.py's /data.json serves ONLY until the real caltex.json exists in the
bucket.

Benchmarks + targets are read from the committed targets/*.csv so they stay in lock-step with the
seed the export job will use for real. Re-run after editing those CSVs:

    .\.venv\Scripts\python.exe clients\client_caltex\gen_placeholder.py
"""
import csv
import json
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "dash", "placeholder.json")
TARGETS_DIR = os.path.join(HERE, "targets")

random.seed(42)  # deterministic: re-running yields the identical file (clean diffs)

# --- flight window (mid-flight, so pacing/goal charts show "in progress") --------------------
FLIGHT_START = date(2026, 7, 14)
FLIGHT_END = date(2026, 9, 30)
DATA_THROUGH = date(2026, 7, 27)         # rows run start..DATA_THROUGH (14 of 79 days elapsed)
DAYS_TOTAL = (FLIGHT_END - FLIGHT_START).days + 1
DAYS_ELAPSED = (DATA_THROUGH - FLIGHT_START).days + 1

CAMPAIGN_ID = "cmp_caltex_qldwa"
CAMPAIGN = "Caltex | Awareness + Consideration | QLD+WA"

# --- ad group (tactic) tree: matches the real TTD ad group names -------------------------------
# weight = share of the ~A$380/day pace; cpm/ctr are per-tactic characters so the tactic
# comparisons have a visible story (standard = cheap reach; attention = engaged, dearer).
AD_GROUPS = [
    {"id": "ag_std", "name": "Display Standard | QLD+WA", "tactic": "Display Standard",
     "stage": "Awareness", "weight": 0.50, "cpm": 3.2, "ctr": 0.0009, "video": False,
     "creatives": [("cr_std_1", "CX_UnstoppableEnergy_300x250", "300x250"),
                   ("cr_std_2", "CX_UnstoppableEnergy_728x90", "728x90"),
                   ("cr_std_3", "CX_UnstoppableEnergy_320x50", "320x50")]},
    {"id": "ag_ai", "name": "AI Contextual | QLD+WA", "tactic": "AI Contextual",
     "stage": "Consideration", "weight": 0.30, "cpm": 6.4, "ctr": 0.0016, "video": False,
     "creatives": [("cr_ai_1", "CX_FuelYourJourney_300x600", "300x600"),
                   ("cr_ai_2", "CX_FuelYourJourney_300x250", "300x250"),
                   ("cr_ai_3", "CX_FuelYourJourney_970x250", "970x250")]},
    {"id": "ag_att", "name": "Attention-Optimised | QLD+WA", "tactic": "Attention-Optimised",
     "stage": "Consideration", "weight": 0.20, "cpm": 9.1, "ctr": 0.0023, "video": True,
     "creatives": [("cr_att_1", "CX_StationStory_15s_Video", "Video 15s"),
                   ("cr_att_2", "CX_StationStory_300x250", "300x250")]},
]
MARKET = "QLD+WA"


def day_factor(i):
    """Mild ramp + weekly seasonality so trend lines look organic (not flat)."""
    ramp = 0.82 + 0.025 * i
    dow = (FLIGHT_START + timedelta(days=i)).weekday()
    week = 1.10 if dow < 5 else 0.84            # weekdays heavier
    return ramp * week


def build_rows():
    rows = []
    dates = [FLIGHT_START + timedelta(days=i) for i in range(DAYS_ELAPSED)]
    for g in AD_GROUPS:
        cr_share = g["weight"] / len(g["creatives"])
        for (cid, cname, fmt) in g["creatives"]:
            for i, d in enumerate(dates):
                jitter = random.uniform(0.85, 1.18)
                spend = round(380.0 * cr_share * day_factor(i) * jitter, 2)
                cpm = g["cpm"] * random.uniform(0.88, 1.14)
                impressions = int(spend / cpm * 1000)
                clicks = int(round(impressions * g["ctr"] * random.uniform(0.75, 1.3)))
                if g["video"] and fmt.startswith("Video"):
                    vs = int(impressions * random.uniform(0.55, 0.7))
                    v25 = int(vs * random.uniform(0.62, 0.74))
                    v50 = int(v25 * random.uniform(0.66, 0.78))
                    v75 = int(v50 * random.uniform(0.7, 0.82))
                    vc = int(v75 * random.uniform(0.78, 0.9))
                else:
                    vs = v25 = v50 = v75 = vc = 0
                # sparse pixel-attributed actions: post-view dominates (upper-funnel display)
                pv = round(impressions * 0.000018 * random.uniform(0, 1.6))
                pc = round(clicks * 0.012 * random.uniform(0, 1.5))
                rows.append({
                    "date": d.isoformat(),
                    "campaign_id": CAMPAIGN_ID, "campaign": CAMPAIGN,
                    "ad_group_id": g["id"], "ad_group": g["name"],
                    "tactic": g["tactic"], "market": MARKET,
                    "creative_id": cid, "creative": cname, "ad_format": fmt,
                    "stage": g["stage"],
                    "spend": spend, "impressions": impressions, "clicks": clicks,
                    "video_starts": vs, "video_25": v25, "video_50": v50, "video_75": v75,
                    "video_completes": vc,
                    "pv_conv": pv, "pc_conv": pc,
                })
    return rows


def read_targets():
    """Mirror seed_static.py: targets.csv -> {key:{value,status}} with numeric values parsed."""
    targets = {}
    with open(os.path.join(TARGETS_DIR, "targets.csv"), newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            raw = r["value"]
            try:
                val = float(raw)
                if val.is_integer():
                    val = int(val)
            except ValueError:
                val = raw
            targets[r["key"]] = {"value": val, "status": r["status"]}
    return targets


def main():
    rows = build_rows()
    targets = read_targets()

    def tv(k):
        v = targets.get(k, {}).get("value")
        return float(v) if isinstance(v, (int, float)) else None

    benchmarks = {
        "cpm": tv("cpm_target_aud"), "ctr": tv("ctr_target"), "cpc": tv("cpc_target_aud"),
        "impressions_target": tv("impressions_target"),
        "daily_pace": tv("daily_pace_aud"), "flight_budget": tv("flight_budget_aud"),
    }
    spend_total = round(sum(r["spend"] for r in rows), 2)
    imps_total = sum(r["impressions"] for r in rows)
    actions_total = round(sum(r["pv_conv"] + r["pc_conv"] for r in rows), 1)
    budget = benchmarks["flight_budget"] or 30000.0
    daily_pace = benchmarks["daily_pace"] or (budget / DAYS_TOTAL)
    flight = {
        "start": FLIGHT_START.isoformat(), "end": FLIGHT_END.isoformat(),
        "budget": budget, "days_total": DAYS_TOTAL, "days_elapsed": DAYS_ELAPSED,
        "daily_pace": daily_pace, "pace_expected": round(daily_pace * DAYS_ELAPSED, 2),
        "projected_spend": round(spend_total / DAYS_ELAPSED * DAYS_TOTAL, 2),
        "spend_to_date": spend_total, "impressions_to_date": imps_total,
        "actions_to_date": actions_total,
    }
    env = {
        "meta": {
            "client": "caltex", "title": "Caltex", "currency": "AUD",
            "placeholder": True,                    # <- the ONLY tell; dashboard shows the sample banner
            "action_source_label": "Sample",
            "channel": "The Trade Desk (programmatic display)",
            "last_updated": DATA_THROUGH.isoformat() + "T08:00:00Z",
            "data_through": DATA_THROUGH.isoformat() + "T08:00:00Z",
            "date_min": rows[0]["date"], "date_max": DATA_THROUGH.isoformat(),
            "row_count": len(rows),
        },
        "flight": flight, "benchmarks": benchmarks, "targets": targets,
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(env, f, separators=(",", ":"))
    print(f"wrote {OUT}")
    print(f"  {len(rows)} rows | {imps_total:,} sample impressions | {actions_total} actions | "
          f"${spend_total:,.0f} spend | {DAYS_ELAPSED}/{DAYS_TOTAL} days")


if __name__ == "__main__":
    main()
