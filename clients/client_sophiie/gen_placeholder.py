r"""Generate dash/placeholder.json - a Sophiie AI-shaped SAMPLE payload for the dashboard.

The Trade Desk campaign SOPHIIE_2026-Q3_TTD_AU_DISPLAY_PROSPECTING is LIVE, but its advertiser
(gjcl0pp) is not yet shared with our Windsor Trade Desk connector, so raw_windsor.perf_the_trade_desk
holds no Sophiie rows and client_sophiie.fact is empty. The export job REFUSES to publish an empty
fact, so dash/main.py keeps serving this payload until the grant lands - at which point the first
*/10 tick publishes the real sophiie.json, the banner clears itself, and nothing here is read again.
See clients/client_sophiie/README.md -> "GO-LIVE".

This file is therefore two things at once:
  1. the SAMPLE the client sees behind a loud "sample data" banner (meta.placeholder = true), and
  2. the written-down DATA CONTRACT - the exact shape job/main.py emits from BigQuery
     (meta / flight / benchmarks / targets / rows[]).

Every number here is synthetic and deterministic (random.seed(42)), but the STRUCTURE is real: the
one live campaign, its four real ad groups, the real flight window, and the real KPI targets read
straight from the committed targets/*.csv so the sample can never contradict the seed the export job
uses. Re-run after editing those CSVs:

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

# --- flight window ----------------------------------------------------------------------------
# The REAL flight, matching targets/targets.csv + targets/budget.csv.
#
# DATA_THROUGH is DERIVED, never hardcoded. It has to sit a few days into the flight so every pacing
# card reads "in progress" rather than "flight over" (a placeholder seeded with an EXPIRED window
# makes every card look failed - a live go-live blocker on two other preview clients; md/AGENTS.md).
# But a fixed date fails the other way just as badly: this was pinned to 2026-09-12 while the real
# campaign had been live two days, so the sample showed 10 days and A$3,009 of delivery - a week of
# it in the FUTURE - on a tile a client can open. Both failures are the same mistake, which is
# pinning a date at all.
#
# So: YESTERDAY - the newest day an ad platform can actually have reported a full day for - capped at
# the flight end. Only BEFORE the flight opens is there no honest "in progress" state to draw, and
# only then does it fall back to a synthetic day 3. Do not apply that floor once the flight is
# running: it pushed DATA_THROUGH to TODAY on day 3, which overstates delivery by a day again.
FLIGHT_START = date(2026, 9, 3)
FLIGHT_END = date(2026, 10, 3)
_YESTERDAY = date.today() - timedelta(days=1)
DATA_THROUGH = (min(FLIGHT_START + timedelta(days=2), FLIGHT_END) if _YESTERDAY < FLIGHT_START
                else min(_YESTERDAY, FLIGHT_END))
# Days at the START of the flight that report ZERO attributed sign-ups, then a 4-day ramp to the
# steady-state CVR. Display attribution simply does not land on day one.
RAMP_DAYS = 5
DAYS_TOTAL = (FLIGHT_END - FLIGHT_START).days + 1
DAYS_ELAPSED = (DATA_THROUGH - FLIGHT_START).days + 1

CAMPAIGN_ID = "5jgf5yn"
CAMPAIGN_NAME = "SOPHIIE_2026-Q3_TTD_AU_DISPLAY_PROSPECTING"

# --- ad groups --------------------------------------------------------------------------------
# The REAL four ad groups. `tier` and `stage` are what sql/01_stg_ttd.sql derives from these names,
# reproduced here so the sample exercises the same parse the live payload will.
#   share = share of spend | ctr = click-through rate | cvr = clicks -> sign-ups
# The rates are tuned so the blended result lands JUST INSIDE all three KPI targets: a sample that
# reads "miles ahead of plan" sets an expectation the real campaign then has to live down, and one
# that reads "failing" is worse. It should show the vs-target logic in its healthy state.
AD_GROUPS = [
    {"id": "ag_t1", "name": "TIER1-CALLHEAVY_AWR", "tier": "Tier 1 - call heavy",
     "stage": "Awareness", "share": 0.34, "ctr": 0.00152, "cvr": 0.0230},
    {"id": "ag_t2", "name": "TIER2-QUOTED_AWR", "tier": "Tier 2 - quoted",
     "stage": "Awareness", "share": 0.26, "ctr": 0.00130, "cvr": 0.0166},
    {"id": "ag_t3", "name": "TIER3-PROJECT_AWR", "tier": "Tier 3 - project work",
     "stage": "Awareness", "share": 0.22, "ctr": 0.00108, "cvr": 0.0120},
    {"id": "ag_rt", "name": "RETARGETING_CONSID", "tier": "Retargeting",
     "stage": "Consideration", "share": 0.18, "ctr": 0.00245, "cvr": 0.0411},
]

# Display banner inventory. The Trade Desk reports creative NAME + AD FORMAT (never an image URL),
# which is why the Creative tab renders branded tiles rather than thumbnails.
CREATIVES = [
    ("cr_300x250_a", "Sophiie_NeverMissACall_300x250", "300x250"),
    ("cr_300x250_b", "Sophiie_AfterHours_300x250", "300x250"),
    ("cr_728x90_a", "Sophiie_NeverMissACall_728x90", "728x90"),
    ("cr_320x50_a", "Sophiie_BookedWhileYouWork_320x50", "320x50"),
    ("cr_160x600_a", "Sophiie_QuoteFollowUp_160x600", "160x600"),
    ("cr_970x250_a", "Sophiie_AIReceptionist_970x250", "970x250"),
]

# --- targets: read from the committed CSVs so the sample can never contradict the seed ----------
def read_targets():
    out = {}
    with open(os.path.join(TARGETS_DIR, "targets.csv"), newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row["value"]
            try:
                val = float(raw)
            except (TypeError, ValueError):
                val = raw
            out[row["key"]] = {"value": val, "status": row["status"]}
    return out


TARGETS = read_targets()


def tval(key, default=None):
    v = (TARGETS.get(key) or {}).get("value")
    return v if isinstance(v, (int, float)) else default


BUDGET = tval("flight_budget_aud", 10000.0)
CPA_T = tval("cpa_target_aud", 150.0)
CPC_T = tval("cpc_target_aud", 3.0)
CTR_T = tval("ctr_target", 0.0015)
CPM_T = tval("cpm_target_aud", 4.5)

# Sample delivery is paced just under plan - a placeholder that reads "miles ahead" is as unhelpful
# as one that reads "failing". Daily spend wobbles +/-18% around the even pace.
DAILY_PACE = BUDGET / DAYS_TOTAL


def build_rows():
    rows = []
    day = FLIGHT_START
    while day <= DATA_THROUGH:
        # a slow ramp over the first three days, as The Trade Desk's pacing algorithm learns
        ramp = min(1.0, 0.45 + 0.28 * (day - FLIGHT_START).days)
        day_spend = DAILY_PACE * ramp * random.uniform(0.82, 1.18)
        for ag in AD_GROUPS:
            ag_spend = day_spend * ag["share"]
            # CPM wobbles around the derived target; impressions follow from spend and CPM
            cpm = CPM_T * random.uniform(0.86, 1.24)
            imps = int(ag_spend / cpm * 1000)
            clicks = int(round(imps * ag["ctr"] * random.uniform(0.8, 1.25)))
            # split the day across 2-3 creatives so the creative tab has something to rank
            picks = random.sample(CREATIVES, random.choice([2, 3]))
            weights = [random.uniform(0.6, 1.4) for _ in picks]
            wsum = sum(weights) or 1.0
            for (cid, cname, fmt), w in zip(picks, weights):
                share = w / wsum
                c_imps = int(imps * share)
                if c_imps <= 0:
                    continue
                c_clicks = int(round(clicks * share))
                # Sign-ups are drawn HERE, at creative grain, not apportioned from an ad-group
                # total: at these counts, rounding a shared total loses ~40% of them.
                #
                # ATTRIBUTION RAMP. A brand-new programmatic display prospecting campaign reports
                # essentially NO attributed sign-ups in its first days - the pixel has to accumulate
                # and the attribution windows have to close. Drawing them from day 1 made the sample
                # claim 6 sign-ups at a A$61 CPA on day 2, i.e. 2.4x BETTER than the A$150 target,
                # which sets a false expectation on a tile a client can open. It also meant the
                # sample never exercised the zero-sign-up state - which is the state the dashboard
                # will ACTUALLY be in on day one (KPIs read "-" and "none attributed yet", and the
                # goal chart switches itself to cumulative impressions).
                _dnum = (day - FLIGHT_START).days          # 0 on the first day of the flight
                _ramp = 0.0 if _dnum < RAMP_DAYS else min(1.0, (_dnum - RAMP_DAYS + 1) / 4.0)
                c_sign = (sum(1 for _ in range(c_clicks) if random.random() < ag["cvr"] * _ramp)
                          if _ramp > 0 else 0)
                # post-view carries most of the credit on a display buy, as it does in reality
                pc = int(round(c_sign * 0.35))
                rows.append({
                    "date": day.isoformat(),
                    "campaign_id": CAMPAIGN_ID, "campaign": CAMPAIGN_NAME,
                    "ad_group_id": ag["id"], "ad_group": ag["name"],
                    "tier": ag["tier"], "market": "Australia",
                    "creative_id": cid, "creative": cname, "ad_format": fmt,
                    "stage": ag["stage"],
                    "spend": round(ag_spend * share, 2),
                    "impressions": c_imps,
                    "clicks": c_clicks,
                    # Banner buy: The Trade Desk reports the video columns as zeros, and the
                    # dashboard hides the video card when nothing is non-zero anywhere.
                    "video_starts": 0, "video_25": 0, "video_50": 0, "video_75": 0,
                    "video_completes": 0,
                    "pv_conv": c_sign - pc, "pc_conv": pc,
                    # Viewability measurement is not enabled on these ad groups, so BOTH sides are
                    # null - which the dashboard must render as "not measured", never as 0% viewable.
                    "vw_viewed": None, "vw_tracked": None,
                })
        day += timedelta(days=1)
    return rows


def main():
    rows = build_rows()
    spend = sum(r["spend"] for r in rows)
    imps = sum(r["impressions"] for r in rows)
    clicks = sum(r["clicks"] for r in rows)
    signups = sum(r["pv_conv"] + r["pc_conv"] for r in rows)
    pace_expected = DAILY_PACE * DAYS_ELAPSED
    env = {
        "meta": {
            "client": "sophiie",
            "title": "Sophiie AI",
            "currency": "AUD",
            "action_source_label": "Sign up · TTD-attributed",
            "channel": "The Trade Desk (programmatic display)",
            # THE ONLY TELL. Real payloads have no such key, so the banner clears itself.
            "placeholder": True,
            "last_updated": f"{DATA_THROUGH.isoformat()}T21:40:00Z",
            "data_through": f"{DATA_THROUGH.isoformat()}T21:40:00Z",
            "date_min": rows[0]["date"], "date_max": rows[-1]["date"],
            "row_count": len(rows),
            # Only the slots that ACTUALLY fired, matching what job/main.py emits: an empty list
            # while nothing has converted. Hardcoding two reporting slots next to zero sign-ups
            # made the sample contradict itself.
            "conversion_slots": (["click_conversion_01", "view_through_conversion_01"]
                                 if signups else []),
        },
        "flight": {
            "start": FLIGHT_START.isoformat(), "end": FLIGHT_END.isoformat(),
            "budget": BUDGET, "days_total": DAYS_TOTAL, "days_elapsed": DAYS_ELAPSED,
            "daily_pace": round(DAILY_PACE, 2), "pace_expected": round(pace_expected, 2),
            "projected_spend": round(spend / DAYS_ELAPSED * DAYS_TOTAL, 2),
            "spend_to_date": round(spend, 2),
            "impressions_to_date": imps, "clicks_to_date": clicks,
            "signups_to_date": signups,
            "vw_viewed_to_date": 0, "vw_tracked_to_date": 0,
        },
        "benchmarks": {
            "cpa": CPA_T, "cpc": CPC_T, "ctr": CTR_T, "cpm": CPM_T,
            "impressions_target": tval("impressions_target"),
            "signups_target": tval("signups_target"),
            "daily_pace": tval("daily_pace_aud"),
            "flight_budget": BUDGET,
        },
        "targets": TARGETS,
        "rows": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(env, f)
    print(f"wrote {OUT}")
    print(f"  {len(rows)} rows | {imps:,} imps | {clicks:,} clicks | {signups} sign-ups | "
          f"${spend:,.2f} spend")
    # CPA is undefined until the first sign-up lands, which is the normal state for the first
    # RAMP_DAYS of the flight - print a dash rather than dividing by zero.
    _cpa = f"${spend/signups:,.2f}" if signups else "- (no sign-up attributed yet)"
    print(f"  CTR {clicks/imps:.4%} (target {CTR_T:.2%}) | CPC ${spend/clicks:,.2f} "
          f"(target ${CPC_T:,.2f}) | CPA {_cpa} (target ${CPA_T:,.0f})")


if __name__ == "__main__":
    main()
