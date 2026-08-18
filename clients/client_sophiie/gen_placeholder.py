r"""Generate dash/placeholder.json - a Sophiie AI-shaped SAMPLE payload for the preview dashboard.

Sophiie AI's campaigns are still being BUILT, so there is no Windsor/BigQuery data for this client
and, by design, no sql/ views and no export job in this folder yet.

TODO(sophiie): when the campaigns launch and the pipeline is built, this payload is the SHAPE that
job/main.py must emit from BigQuery (meta / flight / benchmarks / targets / rows[] / breakdowns[]) -
it is the data contract, written down as a working example. Every number here is synthetic and
deterministic. The single tell is `meta.placeholder = true`, which dashboard.html renders behind a
loud "sample data" banner and which main.py's /data.json serves ONLY until a real sophiie.json
exists in the bucket - at which point the banner clears itself with no code change and no redeploy.

Benchmarks + targets are read from the committed targets/*.csv so the sample can never contradict
the seed the export job will use for real. Re-run after editing those CSVs:

    .\.venv\Scripts\python.exe clients\client_sophiie\gen_placeholder.py
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

# --- flight window ---------------------------------------------------------------------------
# Deliberately a CURRENT, MID-FLIGHT window so every pacing card reads "in progress". The Bell
# Shakespeare / Next Smile placeholders were seeded with a window that has since ended, which makes
# each pacing card read "flight over" - md/AGENTS.md lists that as one of their go-live blockers, so
# it is not worth inheriting. Re-seed these to the real flight the moment the media plan lands
# (targets/targets.csv is the source; these three constants must match it).
FLIGHT_START = date(2026, 8, 3)
FLIGHT_END = date(2026, 10, 26)
DATA_THROUGH = date(2026, 8, 17)         # rows run start..DATA_THROUGH (15 of 85 days elapsed)
DAYS_TOTAL = (FLIGHT_END - FLIGHT_START).days + 1
DAYS_ELAPSED = (DATA_THROUGH - FLIGHT_START).days + 1

# --- campaign / adset / ad tree ---------------------------------------------------------------
# Stage names MUST match dashboard.html STAGE_COLORS: Awareness / Traffic / Conversion / Retargeting.
# Sophiie sells an AI receptionist + back office to trades and service businesses, so the audience
# split is by trade vertical rather than by geography, and the conversion is a free-trial start or a
# demo booking. Campaign naming carries the SOPHIIE_ prefix that prettyCampaign() strips for display.
CAMPAIGNS = [
    {"id": "cmp_awareness", "name": "SOPHIIE_Awareness_NeverMissACall", "stage": "Awareness",
     "weight": 0.26, "cvr": 0.0055, "video": True,
     "adsets": [("ads_aw_1", "Trades - electrical, plumbing & HVAC"),
                ("ads_aw_2", "Trades - roofing, carpentry & landscaping")]},
    {"id": "cmp_traffic", "name": "SOPHIIE_Traffic_HowItWorks", "stage": "Traffic",
     "weight": 0.24, "cvr": 0.011, "video": False,
     "adsets": [("ads_tr_1", "Sole traders & 2-5 person crews"),
                ("ads_tr_2", "Growing service businesses (6-30 staff)")]},
    {"id": "cmp_trial", "name": "SOPHIIE_Conversion_FreeTrial", "stage": "Conversion",
     "weight": 0.34, "cvr": 0.030, "video": False,
     "adsets": [("ads_cv_1", "High-intent - after-hours call handling"),
                ("ads_cv_2", "Lookalike - existing trial starts")]},
    {"id": "cmp_retarget", "name": "SOPHIIE_Retargeting_TrialStart", "stage": "Retargeting",
     "weight": 0.16, "cvr": 0.040, "video": True,
     "adsets": [("ads_rt_1", "Site visitors - 30 day"),
                ("ads_rt_2", "Pricing page - abandoned signup")]},
]

# Two ads per ad set. The copy paraphrases Sophiie's OWN public positioning (an AI receptionist that
# answers calls, books jobs, quotes, invoices and follows up, for trades and service businesses) so
# the Creative tab reads like the real thing - but it is still SAMPLE copy, not approved ad text.
AD_COPY = {
    "Awareness": [("Every missed call is a job someone else wins",
                   "Sophiie answers your phone 24/7, books the job and follows up - so nothing slips while you're on the tools."),
                  ("The back office that never clocks off",
                   "An AI receptionist built for trades and service businesses: calls answered, jobs booked, quotes out the same day.")],
    "Traffic": [("See exactly how Sophiie handles a call",
                 "Hear a real call flow end to end - answered, qualified, booked into your calendar, and confirmed with the customer."),
                ("What Sophiie does after the phone call",
                 "Quotes, invoices, scheduling and follow-ups, handled for you. See the whole workflow in two minutes.")],
    "Conversion": [("Try Sophiie free",
                    "Set up in minutes, keep your existing number, and see how many calls you were missing. No lock-in contract."),
                   ("Book a 15-minute demo",
                    "We'll walk through your call volume, your booking process and what Sophiie would pick up for you.")],
    "Retargeting": [("Still sending calls to voicemail after hours?",
                     "Pick up where you left off - your free trial takes a few minutes to switch on."),
                    ("Your trial is a few clicks away",
                     "Keep your number, keep your workflow. Sophiie just stops the calls going to voicemail.")],
}
DEST = "https://sophiie.ai/"


def day_factor(i):
    """Mild ramp + weekly seasonality so trend lines look organic (not flat)."""
    ramp = 0.86 + 0.010 * i
    dow = (FLIGHT_START + timedelta(days=i)).weekday()
    # Tradies book and browse early morning and at the weekend, so this is a FLATTER week than a
    # B2B office curve - weekends dip, but nothing like the ~0.6 of a corporate audience.
    week = 1.08 if dow < 5 else 0.86
    return ramp * week


def build_rows():
    rows = []
    dates = [FLIGHT_START + timedelta(days=i) for i in range(DAYS_ELAPSED)]
    daily_pace = read_targets_value("daily_pace_aud") or 214.0
    for c in CAMPAIGNS:
        ad_share = c["weight"] / (len(c["adsets"]) * 2)      # split evenly across the 4 ads
        for (aset_id, aset_name) in c["adsets"]:
            for k in range(2):
                ad_id = f"{aset_id}_ad{k+1}"
                title, body = AD_COPY[c["stage"]][k]
                objective = {"Awareness": "OUTCOME_AWARENESS", "Traffic": "OUTCOME_TRAFFIC",
                             "Conversion": "OUTCOME_LEADS", "Retargeting": "OUTCOME_LEADS"}[c["stage"]]
                for i, d in enumerate(dates):
                    jitter = random.uniform(0.85, 1.18)
                    spend = round(daily_pace * ad_share * day_factor(i) * jitter, 2)
                    cpm = random.uniform(7.0, 11.5)
                    impressions = int(spend / cpm * 1000)
                    ctr = random.uniform(0.009, 0.018)
                    link_clicks = int(impressions * ctr)
                    clicks = int(link_clicks * random.uniform(1.15, 1.4))
                    freq = random.uniform(1.4, 2.4)
                    reach = int(impressions / freq)
                    lpv = int(link_clicks * random.uniform(0.62, 0.82))
                    # Stochastic rounding. A per-ad-day expected value sits under 1 for the upper
                    # funnel, and int(round(..)) would floor almost every row to zero - collapsing
                    # the whole funnel. Carrying the fraction as a probability keeps the TOTAL
                    # faithful to cvr while leaving each row integral.
                    exact = lpv * c["cvr"] * random.uniform(0.7, 1.4)
                    leads = int(exact) + (1 if random.random() < (exact - int(exact)) else 0)
                    lw = int(round(leads * 0.72))            # website trial-start form
                    lof = leads - lw                         # Meta lead form
                    if c["video"]:
                        v3 = int(impressions * random.uniform(0.22, 0.34))
                        vc = int(v3 * random.uniform(0.10, 0.22))
                        tp = int(v3 * random.uniform(0.25, 0.40))
                    else:
                        v3 = vc = tp = 0
                    rows.append({
                        "date": d.isoformat(),
                        "campaign_id": c["id"], "campaign": c["name"],
                        "adset_id": aset_id, "adset": aset_name,
                        "ad_id": ad_id, "ad": title[:38],
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
    # Trades skew: strongly male, concentrated 25-54 (business owners and operators).
    ages = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    age_w = [0.06, 0.26, 0.30, 0.23, 0.11, 0.04]
    placements = [("Facebook Feed", 0.32), ("Instagram Feed", 0.20), ("Facebook Reels", 0.16),
                  ("Instagram Reels", 0.15), ("Instagram Stories", 0.11), ("Audience Network", 0.06)]
    for d in dates:
        day_imp = int(random.uniform(38000, 58000))
        for age, w in zip(ages, age_w):
            for gender, gw in (("male", 0.78), ("female", 0.22)):
                imp = int(day_imp * w * gw)
                out.append({
                    "date": d.isoformat(), "breakdown": "age_gender", "seg1": age, "seg2": gender,
                    "impressions": imp, "reach": int(imp / 1.8),
                    "clicks": int(imp * 0.015), "link_clicks": int(imp * 0.012),
                    "spend": round(imp / 1000 * 8.6, 2), "leads": int(imp * 0.0006),
                })
        for name, w in placements:
            imp = int(day_imp * w)
            out.append({
                "date": d.isoformat(), "breakdown": "placement", "seg1": name, "seg2": None,
                "impressions": imp, "reach": int(imp / 1.8),
                "clicks": int(imp * 0.015), "link_clicks": int(imp * 0.012),
                "spend": round(imp / 1000 * 8.6, 2), "leads": int(imp * 0.0005),
            })
    return out


def read_targets():
    """Mirror what seed_static.py will do: targets.csv -> {key:{value,status}}, numerics parsed."""
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


_TARGETS = read_targets()


def read_targets_value(key):
    v = _TARGETS.get(key, {}).get("value")
    return float(v) if isinstance(v, (int, float)) else None


def main():
    rows = build_rows()
    targets = _TARGETS
    tv = read_targets_value

    # benchmarks[] is the flat, dashboard-facing view of targets[]. NOTE the deliberate rename:
    # the template this was cloned from called the lead goal `monthly_lead_target` while every
    # consumer (the KPI sub-label AND the cumulative "on track to goal?" chart) treats it as a
    # WHOLE-FLIGHT number. Here it is `flight_lead_target`, which is what it actually means.
    benchmarks = {
        "cpl": tv("cpl_target_aud"), "cpl_stretch": tv("cpl_stretch_aud"),
        "ctr": tv("ctr_target"), "cpm": tv("cpm_target_aud"), "cpc": tv("cpc_target_aud"),
        "cost_per_lpv": tv("cost_per_lpv_target_aud"), "lead_target": tv("flight_lead_target"),
        "qualified_lead_target": tv("qualified_lead_target"), "daily_pace": tv("daily_pace_aud"),
        "flight_budget": tv("flight_budget_aud"),
    }
    spend_total = round(sum(r["spend"] for r in rows), 2)
    leads_total = sum(r["leads"] for r in rows)
    budget = benchmarks["flight_budget"] or 18000.0
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
            "client": "sophiie", "title": "Sophiie AI", "currency": "AUD",
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
    print(f"  {len(rows)} rows | {leads_total} sample enquiries | ${spend_total:,.0f} spend "
          f"| {DAYS_ELAPSED}/{DAYS_TOTAL} days | {len(env['breakdowns'])} breakdown rows")


if __name__ == "__main__":
    main()
