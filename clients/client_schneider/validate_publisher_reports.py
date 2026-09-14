r"""Validate the hand-keyed publisher-report seeds BEFORE they are loaded into BigQuery.

These two CSVs are the one part of the Schneider pipeline a human retypes every month, from a PDF
or a publisher workbook, so they get the checks the rest of the estate gets from its upstream APIs.
This runs OFFLINE against the committed CSVs (no BigQuery, no credentials) and is wired into both
deploy scripts, so a monthly reload cannot get past a typo.

    .\.venv\Scripts\python.exe clients\client_schneider\validate_publisher_reports.py

WHY HERE AND NOT ONLY IN SQL: sql/26_publisher_report_meta.sql re-asserts the plan join at query
time and the export job WARNs on it, but that warning lands in a Cloud Run log an hour after the
person who made the typo has walked away. This fails on their screen, before the load, and prints
the per-publisher totals so they can be checked straight against the report that was just keyed.
The two layers cover different moments deliberately; the SQL side stays the runtime safety net.

EXIT CODE 1 on any error. Warnings print and do not block.
"""
import os
import sys
from collections import Counter, defaultdict

import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
FACT = os.path.join(DATA, "publisher_reports.csv")
META = os.path.join(DATA, "publisher_report_meta.csv")
PLAN = os.path.join(DATA, "media_plan.csv")
CMAP = os.path.join(DATA, "campaign_map.csv")

# Closed vocabulary - see sql/25_publisher_delivery.sql. ONLY 'impressions' may enter an impression
# total; 'sends' and 'article_views' are delivery in other units; 'rate' is never summed at all.
UNITS = {"impressions", "sends", "article_views", "rate"}
# not_live = booked but not yet running, so a meta row with no delivery rows is EXPECTED for it.
STATUSES = {"complete", "in_progress", "not_live"}

FACT_COLS = ["internal_campaign_id", "publisher", "period_label", "period_start", "period_end",
             "placement_group", "placement", "unit", "metric", "quantity", "clicks",
             "booked_quantity", "note"]
META_COLS = ["seq", "internal_campaign_id", "publisher", "publisher_label", "plan_channel",
             "report_source", "report_label", "report_job", "delivery_status", "status_note",
             "internal_note"]

errors, warnings = [], []


def err(m):
    errors.append(m)


def warn(m):
    warnings.append(m)


def read(path, cols, label, owned=True):
    """`owned` = one of the two files this validator is responsible for; a reference file
    (media_plan / campaign_map) is read for a couple of columns only, so an unlisted column
    there is normal and must not be reported as a surprise."""
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


def num(s, field, where, required=False, integer=True):
    """Blank -> None. A non-numeric value is an error, never a silent NaN."""
    if s == "":
        if required:
            err("%s: %s is required and is blank" % (where, field))
        return None
    try:
        v = float(s)
    except ValueError:
        err("%s: %s is not a number (%r)" % (where, field, s))
        return None
    if integer and abs(v - round(v)) > 1e-9:
        warn("%s: %s is not a whole number (%s)" % (where, field, s))
    return v


def check_meta(meta, plan_lines, known_campaigns, has_plan, status_by_key):
    seen_seq, meta_keys = Counter(), set()
    for i, r in enumerate(meta.itertuples(), start=2):
        where = "publisher_report_meta.csv line %d (%s)" % (i, r.publisher or "?")
        if not r.internal_campaign_id or not r.publisher:
            err("%s: internal_campaign_id and publisher are both required" % where)
            continue
        key = (r.internal_campaign_id, r.publisher.lower())
        if key in meta_keys:
            err("%s: duplicate meta row for %s / %s" % (where, key[0], key[1]))
        meta_keys.add(key)
        status_by_key[key] = (r.delivery_status or "").lower()
        if r.publisher != r.publisher.lower() or " " in r.publisher:
            err("%s: publisher must be a lowercase key with no spaces (got %r)" % (where, r.publisher))
        if not r.publisher_label:
            err("%s: publisher_label is required - it is the card heading" % where)
        if known_campaigns and r.internal_campaign_id not in known_campaigns:
            err("%s: internal_campaign_id %r is not in campaign_map.csv, so its rows would render "
                "on no campaign at all" % (where, r.internal_campaign_id))
        if r.delivery_status and r.delivery_status.lower() not in STATUSES:
            err("%s: delivery_status %r is not one of %s"
                % (where, r.delivery_status, sorted(STATUSES)))
        # A BLANK plan_channel is a real statement ("no plan row"); a WRONG one is a broken join.
        # The two must never be confusable, which is why only one of them is an error.
        if r.plan_channel:
            if has_plan and (r.internal_campaign_id, r.plan_channel.lower()) not in plan_lines:
                err("%s: plan_channel %r matches no line in media_plan.csv for %s. Leave it BLANK "
                    "to declare 'no plan row'; a wrong value silently unpaces a live buy"
                    % (where, r.plan_channel, r.internal_campaign_id))
        else:
            warn("%s: no plan_channel, so this publisher renders flagged 'missing plan row' with no "
                 "pacing. Add a media-plan line and set plan_channel to pace it" % where)
        num(r.seq, "seq", where, required=True)
        seen_seq[r.seq] += 1
    for s, n in seen_seq.items():
        if n > 1:
            err("publisher_report_meta.csv: seq %s used %d times - card order would be arbitrary"
                % (s, n))
    return meta_keys


def check_fact(fact):
    grain, fact_keys = Counter(), set()
    tot = defaultdict(lambda: defaultdict(float))
    for i, r in enumerate(fact.itertuples(), start=2):
        where = "publisher_reports.csv line %d (%s / %s)" % (
            i, r.publisher or "?", r.period_label or "?")
        if not r.internal_campaign_id or not r.publisher:
            err("%s: internal_campaign_id and publisher are both required" % where)
            continue
        key = (r.internal_campaign_id, r.publisher.lower())
        fact_keys.add(key)
        unit = r.unit.lower()
        if unit not in UNITS:
            err("%s: unit %r is not one of %s. An unknown unit is counted in NO total - fix it "
                "rather than letting the row disappear" % (where, r.unit, sorted(UNITS)))
            continue
        for f, v in (("period_start", r.period_start), ("period_end", r.period_end)):
            if not v:
                err("%s: %s is required" % (where, f))
            elif pd.isna(pd.to_datetime(v, errors="coerce", format="%Y-%m-%d")):
                err("%s: %s %r is not a YYYY-MM-DD date" % (where, f, v))
        if r.period_start and r.period_end and r.period_start > r.period_end:
            err("%s: period_start %s is after period_end %s" % (where, r.period_start, r.period_end))
        if not r.period_label:
            err("%s: period_label is required - it is what the card prints" % where)

        if unit == "rate":
            if not r.metric:
                err("%s: a rate row must name its metric (e.g. newsletter_open_rate)" % where)
            v = num(r.quantity, "quantity", where, required=True, integer=False)
            if v is not None and not 0 < v <= 1:
                err("%s: a rate must be a fraction between 0 and 1 (got %s). 54%% is 0.54, not 54"
                    % (where, r.quantity))
            for f, val in (("clicks", r.clicks), ("booked_quantity", r.booked_quantity)):
                if val:
                    err("%s: a rate row must not carry %s - rates are never summed or paced"
                        % (where, f))
        else:
            if r.metric:
                err("%s: metric is only for rate rows (got %r on a %s row)" % (where, r.metric, unit))
            q = num(r.quantity, "quantity", where)   # blank is legal: "not separately reported"
            c = num(r.clicks, "clicks", where)
            b = num(r.booked_quantity, "booked_quantity", where)
            if unit == "article_views" and b is None:
                warn("%s: article_views with no booked_quantity - booked vs delivered cannot be "
                     "shown for this article" % where)
            if unit == "article_views" and q is None and b is not None:
                print("note: %s: booked with nothing delivered yet - counted in booked, not in "
                      "delivered." % where)
            if unit != "article_views" and b is not None:
                warn("%s: booked_quantity on a %s row is only rendered for article_views"
                     % (where, unit))
            tot[key][unit] += q or 0
            tot[key]["clicks"] += c or 0
            if unit == "article_views":
                tot[key]["booked"] += b or 0

        gk = (r.internal_campaign_id, r.publisher.lower(), r.period_label, r.placement_group,
              r.placement, unit, r.metric)
        grain[gk] += 1
    for gk, n in grain.items():
        if n > 1:
            err("publisher_reports.csv: %d rows share the grain key %s / %s / %s / %s - the "
                "publisher reported one line, so sum them into a single row rather than repeating "
                "the key" % (n, gk[1], gk[2], gk[4] or "(no placement)", gk[5]))
    return fact_keys, tot


def main():
    fact = read(FACT, FACT_COLS, "publisher_reports.csv")
    meta = read(META, META_COLS, "publisher_report_meta.csv")
    plan = read(PLAN, ["internal_campaign_id", "channel"], "media_plan.csv", owned=False)
    cmap = read(CMAP, ["internal_campaign_id"], "campaign_map.csv", owned=False)
    if fact is None or meta is None:
        report()
        return

    known_campaigns = set(cmap["internal_campaign_id"]) if cmap is not None else set()
    plan_lines = set()
    if plan is not None:
        plan_lines = set((r.internal_campaign_id, r.channel.lower()) for r in plan.itertuples())

    status_by_key = {}
    meta_keys = check_meta(meta, plan_lines, known_campaigns, plan is not None, status_by_key)
    fact_keys, tot = check_fact(fact)

    # The two files must describe the same publishers, or a card loses its heading / its data.
    for k in sorted(fact_keys - meta_keys):
        err("publisher_report_meta.csv: no meta row for %r on %r, which has delivery rows. Without "
            "one the card has no heading, source or plan match" % (k[1], k[0]))
    for k in sorted(meta_keys - fact_keys):
        st = status_by_key.get(k, "")
        if st == "not_live":
            print("note: %r on %r is marked not_live - a plan line with no report yet, which is the "
                  "point of that status. It renders on the plan table with no card." % (k[1], k[0]))
        else:
            warn("publisher_report_meta.csv: %r on %r has a meta row but no delivery rows yet - it "
                 "will not render a card until a report is keyed in. Set delivery_status=not_live if "
                 "that is deliberate" % (k[1], k[0]))

    # Reconciliation print: check this against the report that was just keyed in.
    if tot:
        print("\nPer-publisher totals - check these against the publisher report:")
        print("  %-18s %12s %8s %8s %9s %8s"
              % ("publisher", "impressions", "clicks", "sends", "articles", "booked"))
        for k in sorted(tot):
            t = tot[k]
            print("  %-18s %12s %8s %8s %9s %8s"
                  % (k[1], format(int(t["impressions"]), ","), format(int(t["clicks"]), ","),
                     format(int(t["sends"]), ","), format(int(t["article_views"]), ","),
                     format(int(t["booked"]), ",")))
        print("  (impressions EXCLUDE solus sends and sponsored-article views by construction)")
    report()


def report():
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
