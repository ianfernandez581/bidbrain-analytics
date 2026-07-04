r"""Generate dash/placeholder.json — a Caltex-branded SAMPLE payload for the placeholder dashboard.

Caltex has NO live data connected yet (onboarding is in progress). This script emits a payload that
matches EXACTLY the JSON contract that job/main.py builds from BigQuery (meta / flight / benchmarks /
targets / rows[] / breakdowns[]), but every number is synthetic + deterministic. The single tell is
`meta.placeholder = true`, which dashboard.html renders behind a loud "sample data" banner and which
main.py's /data.json serves ONLY until the real caltex.json exists in the bucket.

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
FLIGHT_START = date(2026, 6, 21)
FLIGHT_END = date(2026, 7, 20)
DATA_THROUGH = date(2026, 7, 4)          # rows run start..DATA_THROUGH (14 of 30 days elapsed)
DAYS_TOTAL = (FLIGHT_END - FLIGHT_START).days + 1
DAYS_ELAPSED = (DATA_THROUGH - FLIGHT_START).days + 1

# --- campaign / adset / ad tree (4 stages so every chart has variety) ------------------------
# stage names match dashboard.html STAGE_COLORS: Awareness / Traffic / Conversion / Retargeting.
CAMPAIGNS = [
    {"id": "cmp_awareness", "name": "Caltex_Awareness_TechronBrand", "stage": "Awareness",
     "weight": 0.34, "cvr": 0.006, "video": True,
     "adsets": [("ads_aw_1", "Prospecting · Drivers 25-54"), ("ads_aw_2", "Lookalike · Fuel Buyers")]},
    {"id": "cmp_traffic", "name": "Caltex_Traffic_CaltexGO", "stage": "Traffic",
     "weight": 0.24, "cvr": 0.014, "video": False,
     "adsets": [("ads_tr_1", "CaltexGO app installs"), ("ads_tr_2", "Site visitors")]},
    {"id": "cmp_leads", "name": "Caltex_Leads_StarCard", "stage": "Conversion",
     "weight": 0.28, "cvr": 0.052, "video": False,
     "adsets": [("ads_ld_1", "Fleet / StarCard leads"), ("ads_ld_2", "SME fuel accounts")]},
    {"id": "cmp_retarget", "name": "Caltex_Retargeting_Workshop", "stage": "Retargeting",
     "weight": 0.14, "cvr": 0.061, "video": True,
     "adsets": [("ads_rt_1", "Enquiry retarget"), ("ads_rt_2", "Video viewers")]},
]
# Two ads per adset, with Caltex-flavoured creative copy for the gallery fallback tiles.
AD_COPY = {
    "Awareness": [("Techron® Fuels — clean power, every drive",
                   "Unlock better mileage and a cleaner engine with Caltex with Techron®. Fill up at your nearest station."),
                  ("The star you can trust since 1936",
                   "Quality fuel, expert service and Star Mart convenience — that's the Caltex difference.")],
    "Traffic": [("Pay, earn & find stations — the CaltexGO app",
                 "Skip the queue. Pay from your car, collect points and locate the nearest Caltex in seconds."),
                ("Every litre earns you rewards",
                 "Download CaltexGO and start turning fuel-ups into rewards from day one.")],
    "Conversion": [("Fuel your fleet with a Caltex StarCard",
                    "Consolidated billing, spend controls and acceptance across the network. Apply for a StarCard today."),
                   ("Business fuel, simplified",
                    "Cut admin and track every litre with StarCard for SMEs. Talk to our team.")],
    "Retargeting": [("Still thinking it over? Your StarCard is waiting",
                     "Finish your application in minutes and put your fleet fuel on autopilot."),
                    ("Book your next Workshop service",
                     "Trusted Caltex Workshop servicing to keep every vehicle running its best.")],
}
DEST = "https://www.caltex.com/sg/en.html"


def day_factor(i):
    """Mild ramp + weekly seasonality so trend lines look organic (not flat)."""
    ramp = 0.82 + 0.03 * i
    dow = (FLIGHT_START + timedelta(days=i)).weekday()
    week = 1.12 if dow < 5 else 0.78            # weekdays heavier
    return ramp * week


def build_rows():
    rows = []
    dates = [FLIGHT_START + timedelta(days=i) for i in range(DAYS_ELAPSED)]
    # per-ad share of the ~$250/day pace, by campaign weight, split evenly across its 4 ads
    for c in CAMPAIGNS:
        ad_share = c["weight"] / (len(c["adsets"]) * 2)
        for (aset_id, aset_name) in c["adsets"]:
            for k in range(2):
                ad_id = f"{aset_id}_ad{k+1}"
                title, body = AD_COPY[c["stage"]][k]
                objective = {"Awareness": "OUTCOME_AWARENESS", "Traffic": "OUTCOME_TRAFFIC",
                             "Conversion": "OUTCOME_LEADS", "Retargeting": "OUTCOME_LEADS"}[c["stage"]]
                for i, d in enumerate(dates):
                    jitter = random.uniform(0.85, 1.18)
                    spend = round(250.0 * ad_share * day_factor(i) * jitter, 2)
                    cpm = random.uniform(7.5, 12.5)
                    impressions = int(spend / cpm * 1000)
                    ctr = random.uniform(0.010, 0.021)
                    link_clicks = int(impressions * ctr)
                    clicks = int(link_clicks * random.uniform(1.15, 1.4))
                    freq = random.uniform(1.5, 2.6)
                    reach = int(impressions / freq)
                    lpv = int(link_clicks * random.uniform(0.62, 0.82))
                    leads = int(round(lpv * c["cvr"] * random.uniform(0.7, 1.4)))
                    lw = int(round(leads * 0.6))
                    lof = leads - lw
                    if c["video"]:
                        v3 = int(impressions * random.uniform(0.20, 0.32))
                        vc = int(v3 * random.uniform(0.10, 0.22))
                        tp = int(v3 * random.uniform(0.25, 0.4))
                    else:
                        v3 = vc = tp = 0
                    rows.append({
                        "date": d.isoformat(),
                        "campaign_id": c["id"], "campaign": c["name"],
                        "adset_id": aset_id, "adset": aset_name,
                        "ad_id": ad_id, "ad": f"{title[:38]}",
                        "stage": c["stage"],
                        "creative_id": f"cr_{ad_id}", "creative_title": title, "creative_body": body,
                        "creative_thumbnail_url": None,      # None -> branded fallback tile (no broken CDN img)
                        "destination_url": DEST,
                        "spend": spend, "impressions": impressions, "reach": reach,
                        "clicks": clicks, "link_clicks": link_clicks, "lpv": lpv, "leads": leads,
                        "video_3s_views": v3, "video_completes": vc, "thruplays": tp,
                        "leads_website": lw, "leads_onfacebook": lof,
                        "objective": objective, "effective_status": "ACTIVE",
                    })
    return rows


def build_breakdowns():
    out = []
    dates = [FLIGHT_START + timedelta(days=i) for i in range(DAYS_ELAPSED)]
    ages = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    age_w = [0.09, 0.26, 0.24, 0.20, 0.13, 0.08]
    placements = [("Facebook Feed", 0.30), ("Instagram Feed", 0.26), ("Facebook Reels", 0.12),
                  ("Instagram Reels", 0.14), ("Instagram Stories", 0.12), ("Audience Network", 0.06)]
    for d in dates:
        day_imp = int(random.uniform(48000, 72000))
        for age, w in zip(ages, age_w):
            for gender, gw in (("male", 0.58), ("female", 0.42)):
                imp = int(day_imp * w * gw)
                out.append({
                    "date": d.isoformat(), "breakdown": "age_gender", "seg1": age, "seg2": gender,
                    "impressions": imp, "reach": int(imp / 1.9),
                    "clicks": int(imp * 0.016), "link_clicks": int(imp * 0.013),
                    "spend": round(imp / 1000 * 9.5, 2), "leads": int(imp * 0.00035),
                })
        for name, w in placements:
            imp = int(day_imp * w)
            out.append({
                "date": d.isoformat(), "breakdown": "placement", "seg1": name, "seg2": None,
                "impressions": imp, "reach": int(imp / 1.9),
                "clicks": int(imp * 0.016), "link_clicks": int(imp * 0.013),
                "spend": round(imp / 1000 * 9.5, 2), "leads": int(imp * 0.0003),
            })
    return out


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
        "cpl": tv("cpl_target_aud"), "cpl_stretch": tv("cpl_stretch_aud"),
        "ctr": tv("ctr_target"), "cpm": tv("cpm_target_aud"), "cpc": tv("cpc_target_aud"),
        "cost_per_lpv": tv("cost_per_lpv_target_aud"), "lead_target": tv("monthly_lead_target"),
        "qualified_lead_target": tv("qualified_lead_target"), "daily_pace": tv("daily_pace_aud"),
        "flight_budget": tv("flight_budget_aud"),
    }
    spend_total = round(sum(r["spend"] for r in rows), 2)
    leads_total = sum(r["leads"] for r in rows)
    budget = benchmarks["flight_budget"] or 7500.0
    daily_pace = benchmarks["daily_pace"] or (budget / DAYS_TOTAL)
    flight = {
        "start": FLIGHT_START.isoformat(), "end": FLIGHT_END.isoformat(),
        "budget": budget, "days_total": DAYS_TOTAL, "days_elapsed": DAYS_ELAPSED,
        "daily_pace": daily_pace, "pace_expected": round(daily_pace * DAYS_ELAPSED, 2),
        "projected_spend": round(spend_total / DAYS_ELAPSED * DAYS_TOTAL, 2),
        "spend_to_date": spend_total, "leads_to_date": leads_total,
    }
    env = {
        "meta": {
            "client": "caltex", "title": "Caltex", "currency": "AUD",
            "placeholder": True,                    # <- the ONLY tell; dashboard shows the sample banner
            "lead_source_label": "Sample", "channel": "Meta (Facebook + Instagram)",
            "last_updated": DATA_THROUGH.isoformat() + "T08:00:00Z",
            "data_through": DATA_THROUGH.isoformat() + "T08:00:00Z",
            "date_min": rows[0]["date"], "date_max": DATA_THROUGH.isoformat(),
            "row_count": len(rows),
        },
        "flight": flight, "benchmarks": benchmarks, "targets": targets,
        "rows": rows, "breakdowns": build_breakdowns(),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(env, f, separators=(",", ":"))
    print(f"wrote {OUT}")
    print(f"  {len(rows)} rows | {leads_total} sample leads | ${spend_total:,.0f} spend "
          f"| {DAYS_ELAPSED}/{DAYS_TOTAL} days | {len(env['breakdowns'])} breakdown rows")


if __name__ == "__main__":
    main()
