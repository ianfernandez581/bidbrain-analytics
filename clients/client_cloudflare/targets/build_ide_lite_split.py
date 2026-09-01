"""Rebuild the EMEA Roverpath / Final Funnel target rows in cs_targets_q3.csv from the plan's
IDE Lite line.

The approved "Cloudflare EMEA - Q3 Content Syndication Pacing.xlsx" (tab `Media Plan 29-07-26`)
carries an IDE Lite partner totalling 2,565 leads, and the plan's own notes say "IDE Lite is
Rover Path and Final Funnel". The client has NOT yet said how it splits between the two
Salesforce vendors, so this script applies an INTERIM split in proportion to delivery to date
(Calvin, 2026-08-31) and the dashboard labels it as interim in the publisher-table footnote.

WHEN JADE CONFIRMS THE SPLIT: change IDE_LITE_SPLIT below (weights - counts, percentages and
ratios all work), rerun this script, reseed (seed_static.py or bq load) and force the export
job. Nothing else moves: per-line plan totals and the 2,565 grand total are preserved exactly
by construction.

Week mapping matches the streams 2&3 rows: plan week N (Mon 2026-08-03 grid) -> seed week N
(Fri 2026-08-07 grid); each plan line spreads its total evenly over its live weeks (that is
how the plan itself paces: L/13, L/10, L/9), rounded cumulatively so every line total is exact.
"""
import csv, datetime, collections, os

# ---- THE ONE CONFIG VALUE: relative weights of the IDE Lite split -------------------------
# Interim = EMEA Q3 delivery to date at 2026-08-31 (Roverpath 271 leads, Final Funnel 148).
IDE_LITE_SPLIT = {'Roverpath': 271, 'Final Funnel': 148}
# -------------------------------------------------------------------------------------------

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cs_targets_q3.csv')
MARKET_SEQ = {'UKI': 1, 'DACH': 2, 'SEUR': 3, 'NEUR': 4, 'CEERI': 5, 'MEA': 6}
FRI_ANCHOR = datetime.date(2026, 8, 7)
ALL_M = list(MARKET_SEQ)

# IDE Lite plan lines from `Media Plan 29-07-26` (market, line total, first live plan week);
# each line runs from its first week through week 13, evenly. Verified against the workbook
# 2026-08-31 (blocks: CF1 ACQ x3, Modernize Security x3, Closed Lost x2; EXP/Retail/BFSI are 0).
IDE_LITE_LINES = (
    [('UKI', 100, 1), ('DACH', 80, 1), ('SEUR', 130, 1), ('NEUR', 100, 1), ('CEERI', 240, 1), ('MEA', 180, 1)]
    + [(m, 40, 4) for m in ALL_M]
    + [(m, 40, 5) for m in ALL_M]
    + [('NEUR', 90, 4), ('CEERI', 164, 4), ('MEA', 137, 4)]
    + [(m, 32, 4) for m in ALL_M]
    + [(m, 32, 5) for m in ALL_M]
    + [(m, 40, 5) for m in ALL_M]
    + [(m, 40, 5) for m in ALL_M]
)
assert sum(l[1] for l in IDE_LITE_LINES) == 2565, 'IDE Lite plan lines must total 2,565'

share = {v: w / sum(IDE_LITE_SPLIT.values()) for v, w in IDE_LITE_SPLIT.items()}
vendors = list(IDE_LITE_SPLIT)

agg = collections.defaultdict(int)   # (vendor, market, week) -> target
for market, total, first_wk in IDE_LITE_LINES:
    # split the LINE total into integers first (largest share absorbs the rounding), then
    # spread each vendor's integer share evenly over the line's live weeks, cumulative-rounded
    v_tot, assigned = {}, 0
    for i, v in enumerate(vendors):
        v_tot[v] = total - assigned if i == len(vendors) - 1 else round(total * share[v])
        assigned += v_tot[v]
    nweeks = 13 - first_wk + 1
    for v in vendors:
        cum, prev = 0.0, 0
        for wk in range(first_wk, 14):
            cum += v_tot[v] / nweeks
            x = round(cum) - prev
            prev += x
            if x:
                agg[(v, market, wk)] += x

new_rows = []
for v in vendors:
    for wk in range(1, 14):
        for m, seq in sorted(MARKET_SEQ.items(), key=lambda kv: kv[1]):
            t = agg.get((v, m, wk), 0)
            if t > 0:
                ws = (FRI_ANCHOR + datetime.timedelta(days=7 * (wk - 1))).isoformat()
                new_rows.append(f'Core DG,EMEA,{v},{m},{seq},{wk},{ws},{t}')

by_vendor = collections.Counter()
for r in new_rows:
    p = r.split(',')
    by_vendor[p[2]] += int(p[7])
print('IDE Lite split rows:', len(new_rows), '| per vendor:', dict(by_vendor),
      '| total:', sum(by_vendor.values()))
assert sum(by_vendor.values()) == 2565

# idempotent rewrite: drop any existing EMEA rows for these vendors, insert the fresh set
# ahead of the first other EMEA row
lines = open(CSV_PATH, newline='').read().splitlines()
hdr, body = lines[0], lines[1:]
mine = lambda l: any(l.startswith(f'Core DG,EMEA,{v},') for v in vendors)
kept = [l for l in body if not mine(l)]
first_emea = next((i for i, l in enumerate(kept) if l.startswith('Core DG,EMEA,')), len(kept))
out = kept[:first_emea] + new_rows + kept[first_emea:]
open(CSV_PATH, 'w', newline='').write(hdr + '\n' + '\n'.join(out) + '\n')

emea_tot = sum(int(l.split(',')[7]) for l in out if l.startswith('Core DG,EMEA,'))
print(f'wrote {CSV_PATH}: {len(out) + 1} lines | EMEA total target now {emea_tot} (expect 12058)')
