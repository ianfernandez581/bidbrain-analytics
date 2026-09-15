r"""Validate the hand-keyed publisher-report seeds BEFORE they are loaded into BigQuery.

These two CSVs are the one part of the Schneider pipeline a human retypes every month, from a PDF
or a publisher workbook, so they get the checks the rest of the estate gets from its upstream APIs.
This runs OFFLINE against the committed CSVs (no BigQuery, no credentials) and is wired into all
three deploy scripts, so a monthly reload cannot get past a typo.

    .\.venv\Scripts\python.exe clients\client_schneider\validate_publisher_reports.py

r2 (2026-09-15): the fact file is the account team's own normalised export
(data/aet_publisher_reports_normalized.csv) - wide measure columns, one row per publisher x product
x placement x month, rates stated as PERCENTAGES. sql/25 maps it onto the model the tab renders.

WHY HERE AND NOT ONLY IN SQL: sql/26 re-asserts the plan join at query time and the export job WARNs
on it, but that warning lands in a Cloud Run log an hour after the person who made the typo has
walked away. This fails on their screen, before the load, and prints the per-publisher totals so
they can be checked straight against the report that was just keyed.

EXIT CODE 1 on any error. Warnings print and do not block.
"""
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FACT = os.path.join(DATA, "aet_publisher_reports_normalized.csv")
META = os.path.join(DATA, "publisher_report_meta.csv")
PLAN = os.path.join(DATA, "media_plan.csv")
CMAP = os.path.join(DATA, "campaign_map.csv")

# Closed vocabulary - see sql/25_publisher_delivery.sql. product_type is what decides which total a
# row may enter; anything outside this list is counted in NO total.
UNIT_OF = {
    "content_newsletter": "impressions", "content_web": "impressions",
    "adv_newsletter": "impressions", "adv_display": "impressions",
    "solus_edm": "sends", "sponsored_article": "article_views",
}
STATUSES = {"complete", "in_progress", "not_live"}

FACT_COLS = ["report_month", "job_number", "publisher", "product_type", "placement_name",
             "start_date", "end_date", "impressions", "clicks", "sends", "open_rate",
             "viewability", "booked_views", "delivered_views"]
META_COLS = ["seq", "internal_campaign_id", "publisher", "publisher_label", "plan_channel",
             "report_source", "report_label", "report_job", "delivery_status",
             "booked_article_views", "status_note", "internal_note"]

errors, warnings, notes = [], [], []


def err(m):
    errors.append(m)


def warn(m):
    warnings.append(m)


def read(path, cols, label, owned=True):
    """`owned` = one of the two files this validator is responsible for; a reference file is read
    for a couple of columns only, so an unlisted column there is normal."""
    if not os.path.exists(path):
        err("%s: missing file %s" % (label, path))
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in cols if c not in df.columns]
    if missing:
        err("%s: missing column(s) %s" % (label, ", ".join(missing)))
        return None
    extra = [c for c in df.columns if c not in cols]
    if owned and extra:
        warn("%s: unexpected column(s) %s (ignored by load_seeds.py)" % (label, ", ".join(extra)))
    for c in cols:
        df[c] = df[c].astype(str).str.strip()
    return df


def num(s, field, where, integer=True):
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        err("%s: %s is not a number (%r)" % (where, field, s))
        return None
    if integer and abs(v - round(v)) > 1e-9:
        warn("%s: %s is not a whole number (%s)" % (where, field, s))
    return v


def check_fact(fact):
    grain, keys = Counter(), set()
    tot = defaultdict(lambda: defaultdict(float))
    for i, r in enumerate(fact.itertuples(), start=2):
        where = "aet_publisher_reports_normalized.csv line %d (%s / %s)" % (
            i, r.publisher or "?", r.placement_name or "?")
        if not r.publisher:
            err("%s: publisher is required - it is the join key onto the meta file, and the export "
                "carries no campaign column, so a row without it can resolve no campaign" % where)
            continue
        key = r.publisher.lower()
        keys.add(key)
        pt = r.product_type.lower()
        if pt not in UNIT_OF:
            err("%s: product_type %r is not one of %s. An unknown product type is counted in NO "
                "total - classify it in sql/25 rather than letting the row disappear"
                % (where, r.product_type, sorted(UNIT_OF)))
            continue
        unit = UNIT_OF[pt]

        if not r.report_month:
            err("%s: report_month is required" % where)
        elif pd.isna(pd.to_datetime(r.report_month, errors="coerce", format="%Y-%m-%d")):
            err("%s: report_month %r is not a YYYY-MM-DD date" % (where, r.report_month))
        for f, v in (("start_date", r.start_date), ("end_date", r.end_date)):
            if v and pd.isna(pd.to_datetime(v, errors="coerce", format="%Y-%m-%d")):
                err("%s: %s %r is not a YYYY-MM-DD date" % (where, f, v))
        if r.start_date and r.end_date and r.start_date > r.end_date:
            err("%s: start_date %s is after end_date %s" % (where, r.start_date, r.end_date))

        imp = num(r.impressions, "impressions", where)
        clk = num(r.clicks, "clicks", where)
        snd = num(r.sends, "sends", where)
        bkd = num(r.booked_views, "booked_views", where)
        dlv = num(r.delivered_views, "delivered_views", where)
        # Rates are stated as PERCENTAGES in this export (54, 26.75) and divided by 100 in sql/25.
        for f, v in (("open_rate", r.open_rate), ("viewability", r.viewability)):
            x = num(v, f, where, integer=False)
            if x is not None and not 0 < x <= 100:
                err("%s: %s %s is out of range - this export states rates as PERCENTAGES, so 54%% "
                    "is 54, not 0.54" % (where, f, v))
            if x is not None and x <= 1:
                warn("%s: %s is %s - suspiciously low for a percentage. If that is a fraction it "
                     "will be divided by 100 again and render as %s%%" % (where, f, v, x / 100))

        if unit == "sends" and snd is None:
            err("%s: a solus_edm row must carry sends" % where)
        if unit == "article_views" and dlv is None and bkd is None:
            err("%s: a sponsored_article row must carry booked_views and/or delivered_views" % where)
        if unit == "impressions" and imp is None and clk is None:
            warn("%s: neither impressions nor clicks - the row contributes nothing" % where)
        if unit != "sends" and snd is not None:
            err("%s: sends on a %s row would be counted as eDM despatches" % (where, pt))
        if unit != "article_views" and (bkd is not None or dlv is not None):
            err("%s: booked/delivered views on a %s row are only rendered for sponsored_article"
                % (where, pt))
        if unit == "impressions" and imp is None and clk is not None:
            notes.append("%s: clicks with no impressions - a shared send or a paired position. "
                         "Counted, never dropped." % where)

        tot[key]["impressions"] += imp or 0 if unit == "impressions" else 0
        tot[key]["sends"] += snd or 0 if unit == "sends" else 0
        tot[key]["article_views"] += dlv or 0 if unit == "article_views" else 0
        tot[key]["booked"] += bkd or 0 if unit == "article_views" else 0
        tot[key]["clicks"] += clk or 0
        if unit == "article_views":
            tot[key]["articles"] += 1

        grain[(key, r.report_month, pt, r.placement_name, r.start_date, r.end_date)] += 1
    for gk, c in grain.items():
        if c > 1 and gk[2] != "adv_display":
            warn("aet_publisher_reports_normalized.csv: %d rows share %s / %s / %s / %s - fine if "
                 "the publisher really reported them separately, otherwise sum them"
                 % (c, gk[0], gk[1], gk[2], gk[3] or "(no placement)"))
    return keys, tot


def check_meta(meta, plan_lines, known_campaigns, has_plan):
    seen_seq, keys, status = Counter(), set(), {}
    for i, r in enumerate(meta.itertuples(), start=2):
        where = "publisher_report_meta.csv line %d (%s)" % (i, r.publisher or "?")
        if not r.internal_campaign_id or not r.publisher:
            err("%s: internal_campaign_id and publisher are both required" % where)
            continue
        key = r.publisher.lower()
        if key in keys:
            err("%s: duplicate meta row for %r" % (where, r.publisher))
        keys.add(key)
        status[key] = r.delivery_status.lower()
        if not r.publisher_label:
            err("%s: publisher_label is required - it is the card heading" % where)
        if known_campaigns and r.internal_campaign_id not in known_campaigns:
            err("%s: internal_campaign_id %r is not in campaign_map.csv, so its rows would render "
                "on no campaign at all" % (where, r.internal_campaign_id))
        if r.delivery_status and r.delivery_status.lower() not in STATUSES:
            err("%s: delivery_status %r is not one of %s"
                % (where, r.delivery_status, sorted(STATUSES)))
        if r.plan_channel:
            if has_plan and (r.internal_campaign_id, r.plan_channel.lower()) not in plan_lines:
                err("%s: plan_channel %r matches no line in media_plan.csv for %s. Leave it BLANK "
                    "to declare 'no plan row'; a wrong value silently unpaces a live buy"
                    % (where, r.plan_channel, r.internal_campaign_id))
        else:
            warn("%s: no plan_channel, so this publisher renders flagged 'missing plan row' with no "
                 "pacing" % where)
        num(r.seq, "seq", where)
        if not r.seq:
            err("%s: seq is required - it is the card order" % where)
        num(r.booked_article_views, "booked_article_views", where)
        seen_seq[r.seq] += 1
    for s, c in seen_seq.items():
        if c > 1:
            err("publisher_report_meta.csv: seq %s used %d times - card order would be arbitrary"
                % (s, c))
    return keys, status


def main():
    fact = read(FACT, FACT_COLS, "aet_publisher_reports_normalized.csv")
    meta = read(META, META_COLS, "publisher_report_meta.csv")
    plan = read(PLAN, ["internal_campaign_id", "channel"], "media_plan.csv", owned=False)
    cmap = read(CMAP, ["internal_campaign_id"], "campaign_map.csv", owned=False)
    if fact is None or meta is None:
        report()
        return

    known = set(cmap["internal_campaign_id"]) if cmap is not None else set()
    plan_lines = set()
    if plan is not None:
        plan_lines = set((r.internal_campaign_id, r.channel.lower()) for r in plan.itertuples())

    fact_keys, tot = check_fact(fact)
    meta_keys, status = check_meta(meta, plan_lines, known, plan is not None)

    # The export carries no campaign column, so a publisher with no meta row can resolve no campaign
    # and renders nowhere at all. That is the one failure here that is completely silent on screen.
    for k in sorted(fact_keys - meta_keys):
        err("publisher_report_meta.csv: no row for publisher %r, which HAS delivery rows. The "
            "export carries no campaign column, so without a meta row its campaign cannot be "
            "resolved and every one of its rows is dropped" % k)
    for k in sorted(meta_keys - fact_keys):
        if status.get(k) == "not_live":
            notes.append("%r is marked not_live - a plan line with no report yet, which is the "
                         "point of that status. It renders on the plan table with no card." % k)
        else:
            warn("publisher_report_meta.csv: %r has a meta row but no delivery rows. Set "
                 "delivery_status=not_live if that is deliberate" % k)

    if tot:
        print("\nPer-publisher totals - check these against the publisher report:")
        print("  %-42s %12s %8s %8s %9s %8s %8s"
              % ("publisher", "impressions", "clicks", "sends", "articles", "views", "booked"))
        for k in sorted(tot):
            t = tot[k]
            print("  %-42s %12s %8s %8s %9s %8s %8s"
                  % (k, format(int(t["impressions"]), ","), format(int(t["clicks"]), ","),
                     format(int(t["sends"]), ","), int(t["articles"]),
                     format(int(t["article_views"]), ","), format(int(t["booked"]), ",")))
        print("  (impressions EXCLUDE solus sends and sponsored-article views by construction;")
        print("   `booked` is what the PUBLISHED articles booked - the flight booking is")
        print("   booked_article_views in publisher_report_meta.csv)")
    report()


def report():
    for m in notes:
        print("note: %s" % m)
    for w in warnings:
        print("WARNING: %s" % w)
    for e in errors:
        print("ERROR:   %s" % e)
    if errors:
        print("\n%d error(s), %d warning(s). Seeds NOT safe to load." % (len(errors), len(warnings)))
        sys.exit(1)
    print("\nOK - publisher report seeds valid (%d warning(s))." % len(warnings))


if __name__ == "__main__":
    main()
