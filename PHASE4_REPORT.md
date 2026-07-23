# PHASE 4 REPORT — hardening + tonight's anomalies

**Date:** 2026-07-23 · **Scope:** grid-core · **Playbook:** `grid-core/GRID_BUILD_PLAYBOOK.md` Phase 4 + the Mission-2 anomaly list

**Status: ALL 8 ITEMS COMPLETE.** Each item is its own commit on `desktop-2jvv4oj/work`
(1: `82062ed`, 2: `30add77`, 3: `0944df4`, 4: `e2b0ecb`, 5: `97bfda8`, 6: `47a2776`,
7: `9758b89`, 8: `b196924`). Full test suite green after every item
(**8 suites / 160 assertions**, incl. two new suites added this phase). Standing rules
honored: `calc.js` byte-identical; the one DB-value change (item 3) is STAGED, not applied;
no global sync was run (the only sync call was the sanctioned `?client=Cloudflare` test,
after the fix passed code review + the hermetic suite).

---

## Item 1 — the `?client=` sync bug is FIXED (the §9 corruption vector is closed)

`POST /api/central/sync?client=<name>` now **honors the param**:

- Case-insensitive match on the spec's `client` field; the canonical spelling is used.
- The fetcher is invoked `central_sync.py --client <name>` (new mode), so other clients'
  BQ tables are **never even queried** — the scope is enforced at fetch AND at write.
- Unknown name → **400** `unknown client '<X>' — not in central-clients.json; nothing was synced`.
- Validated-false name → **400** `client '<X>' is not validated — … nothing was synced`.
- `?includeEnded=1` combines with the filter. No param = all validated clients (unchanged).
- `CENTRAL_LAST_SYNC` + the log line + `skippedClients[]` all record the filter.

**Test evidence (live server, fresh process on a dedicated port — heeding the §1b
stale-process lesson; old test server killed after):**

```
POST /api/central/sync?client=NotARealClient
{"error":"unknown client 'NotARealClient' — not in central-clients.json; nothing was synced"}
HTTP 400

POST /api/central/sync?client=PropTrack
{"error":"client 'PropTrack' is not validated — approve its mapping in the Map client panel first; nothing was synced"}
HTTP 400

POST /api/central/sync?client=Cloudflare&includeEnded=1     → HTTP 200
perClient keys: ["Cloudflare"]           ← ONLY Cloudflare
perClient:      {"Cloudflare":{"updated":14,"skipped":0,"bqRows":72}}
skipped:        Schneider + 14 others, all "not requested (client filter)"
Schneider bq rows lastSyncedAt: all still the OLD 2026-07-23T02:20:07 stamps — untouched
```

Plus a new **hermetic regression suite** `src/central/sync-client-filter.test.js` (13
assertions): boots the real server against a temp DB + fixture + temp config and locks the
filter, both 400 paths, the includeEnded combination, and the unchanged no-param behaviour.
Wired into `npm test`.

**⚠ Deployment note:** the long-running grid server process must be **restarted** to pick
this up — an old `node server.js` keeps the global-sync behaviour in memory (the exact §1b
stale-process trap). The local server on :8787 was restarted as part of this phase's close.

## Item 2 — EAE DV360 diagnosis: **not approved — human decision pending** (sync behaved correctly)

- Schneider's `map[]` in `central-clients.json` contains **16 entries — 8 Trade Desk + 8
  LinkedIn, zero DV360**. The EAE Consideration/Conversion pairs are the 2 medium-confidence
  pairs the human deliberately left unticked at approval (PHASE3_SCHNEIDER §9). The sync
  writes only mapped rows, so the 02:20 sync **correctly** skipped them; all 16 approved
  pairs DID sync at 02:20 (16 `bq` rows verified in the DB).
- Not an `Ended` issue, not a channel-spelling issue, not an IO-grain issue — the staged
  pairs (still in `config/reconcile-staged/Schneider.json`) carry the right channel
  (`DV360`) and both campaignIds still resolve. Nothing to fix in the sync path.
- The `spendMult=1` + `platformMargin=0.6` on both rows came from the previously untracked
  `scripts/eae-dv360-fix.js` (now committed for audit). **Governance caveat:** it wrote via
  direct SQLite, bypassing `db.updateCampaignField` — no `central_rows` provenance exists
  for those writes, and a DB rebuild resets both fields to null (benign: null spendMult
  leaves clientSpend untouched; null platformMargin degrades loudly). Re-run the prep after
  any rebuild, or redo it through the governed path.
- **Human path when ready:** tick the 2 EAE pairs in the Map client panel, then backfill
  once with `POST /api/central/sync?client=Schneider&includeEnded=1` (now safely scoped
  per item 1). Note EAE Conversion's sheet clientSpent ($1,804) sits 47% below the billed
  figure — the staged warning still stands: confirm which figure the agency wants recorded.

## Item 3 — margin anomalies: sheet-typed literals; correction STAGED (not applied)

**Trace.** Both values come verbatim from the agency sheet — `'sample data/Central
Updated.xlsx'`, tab `Live Campaigns`:

- **EBA · TradeDesk row 65:** Platform Margin cell = literal `0.9729` (no formula).
- **Software First EcoStruxure · TradeDesk row 71:** literal `0.843` (no formula).

They were imported verbatim (`build_central_import.js` sanity-checks only the 0..1 range)
and are NOT a Grid derivation. They also contradict the sheet's own vintage figures:
`1 − media/billed` gives **0.6557** (EBA: 2,959.71/8,596.57) and **0.6708** (Eco:
854.86/2,596.44) — squarely in the standard band. The typed values imply media costs of
~$233 / ~$408 against those billed figures, i.e. a margin computed from a much earlier
spend snapshot and never refreshed. (Bonus finding while in the sheet: the Campaign Margin
column's formulas divide by absolute `$V$65` — EBA's own Client-spent cell — on every row;
that is the known "17-row $V$65 bug" the importer already discards.)

**Profit-at-risk currently shown (via the frozen `calc.js` `computeRow`, 2026-07-23):**

| Row | Pace | projState | profitAtRisk | atStake |
|---|---|---|---|---|
| EBA · TradeDesk (PM 0.9729) | On (60% spent / 55% elapsed) | over (+$1,781 projected) | **null** | $1,781 (overrun) |
| SF EcoStruxure · TradeDesk (PM 0.843) | On | onplan (+$352) | **null** | $352 |

So **today the anomalous margins put $0 of error on screen** — both rows project at/over
budget and profit-at-risk only fires on under-pacing. The exposure is forward-looking: the
moment either under-paces, every shortfall dollar is booked at 97%/84% margin instead of
~60% (profit-at-risk overstated ~62% / ~40%), and marginDelta/marginBand read against a
false bar today.

**Recommendation + staged correction:** set both to **0.60** (the agency's standard
Schneider TTD margin; all 6 other mapped Schneider TTD rows are 0.60), after confirming
with the sheet owner (Zhen). `scripts/margin-anomaly-fix.js` stages it: **dry-run by
default, writes only with `--apply`**, uses the governed `db.updateCampaignField` path
(provenance in `central_rows`), patches `central-import.json` for rebuild durability, and
read-back-verifies every write. **No DB value was changed this phase.**

## Item 4 — staleness / freshness UX

- **`src/central/staleness.js` (NEW)** — THE single config location: `STALE_WARN_MS = 6h`,
  `STALE_RED_MS = 24h`, plus `classify()` / `agoLabel()` / `clientSyncState()`. States:
  `never / fresh / warn / red`; a client whose rows are all sheet-import is **`never`
  (never synced), not fresh**; `mixed` = live+sheet rows in one client. 19-assertion unit
  suite locks the thresholds and rollup.
- **Central:** the local 4h `STALE_MS` is gone; the last-synced pill tiers amber (>6h) /
  red (>24h / never) with an age label; per-client group rows carry `NO SYNC` / `N SHEET` /
  age chips; a sheet-import row inside an otherwise-synced client gets an **amber SHEET
  tag + amber row edge** with a "NOT covered by the sync" tooltip — the §9 containment
  state can no longer hide (today that lights up Schneider's 9 unsynced rows: EAE ×2,
  IA Services, SF EcoStruxure LinkedIn ×2 not-launched, Heavy Industries ×2, AET Google
  Ads, DOOH).
- **Pulse:** the client rail shows a compact per-client flag (`∅` never-synced / age chip /
  `N✎` unsynced-rows) with tooltips; the single-client context heading shows the full
  flags; the table's LIVE badge gained an amber SHEET twin on mixed-state rows.
- **Executive:** each card joins to its Central client (normalized-name match, no guessing
  on miss) and shows `NEVER SYNCED` / `GRID <age>` / `N UNSYNCED` chips beside the agency
  label — a sheet-only client can never read as fresh.

## Item 5 — SQI removed, Optimization Log kept

`siteQualityCard()` + `scorePill()` + the shell call + the `manage-list` handler removed
from `src/brain/brain-landing.js`; the `.bt-sqi`/`.bt-score` CSS removed from
`the-grid.html`. The Optimization Log card is untouched. **`calc.js` contained no SQI
logic** — the removal was UI-only, exactly as the standing rule hoped. Orphan sweep done:
README/GRID_INVENTORY updated. Deliberately KEPT: the `site_quality` **recommendation
type** in `config/brain-mock-data.js` — that is the Brain recommendations table's
"Blacklist low-quality inventory" mock rec category, a different feature from the SQI card.

## Item 6 — Executive KPI stubs: 2 resolved (one with a real card fix), 5 deferred

**Resolved (validated clients; field paths verified against the LIVE `data.json` in GCS +
the DB keyKpi strings):**

- **Cloudflare — the verification found the card materially WRONG and it is now fixed.**
  The headline (`qoq.q3.accepted` = 394) was correct, but: (a) the target summed the
  per-lead-replicated `ALLOCATED_TARGET` column to **5,506 — the whole-YEAR plan total** —
  so a Q3-only actual displayed as **7% pace**; (b) the trend series filtered on `STATUS`
  (null on 97% of rows) with `LEAD_VALUE` (0 on accepted) — **the spark was empty**.
  Fixed `ex_cloudflare` in `build_exec_kpis.py`: target = `SUM(q3)` over
  `transmission.pacing.rows`, the canonical market×tier plan table (**2,290**; its q2 sum
  is 3,216 = exactly the dashboard's documented Q2 plan — strong confirmation), series =
  weekly count of `LEAD_STATUS='Accepted'` rows, + even pace-to-date over the Q3 window.
  Baked `exec-kpis.json` regenerated from fresh data via the module's own pipeline: the
  card now reads **394 / 2,290 · 71% of expected pace to date · trending up** (was
  394 / 5,506 · 7%). DB cross-check: `Q3 Core DG · LinkedIn "210 Leads"` (+ Google Ads
  42) are the PAID-media lead targets — a different funnel from CS accepted, consistent
  with the card measuring the CS lane.
- **Schneider — verified correct as-built.** `campaigns[].leads/target` over the 4
  lead-gen programs (641 / 1,117 at verification), `cs_weekly` series, per-flight even
  pace. NEL (`keyKpi "0.10% CTR"`) + global_rebrand are awareness programs (target 0)
  and are correctly excluded from the lead KPI. Stub removed; verification recorded in
  the kpi object.

**Deferred (not-yet-validated: hireright, mongodb, proptrack, tlm, vmch):** `"stub": true`
kept; each file gained an `_exec_field_path_intended` note with the exact intended path
(hireright has **no Executive card at all** yet — flagged as such). Resolve each as
Mission 1 validates the client.

## Item 7 — README corrected

`grid-core/README.md` no longer describes pre-rebuild behaviour: the
`build_grid_data.py`/`live_metrics.py` overlay section is replaced by the Central-sync
reality; **Mode B is documented as THE spec standard** (Mode A demoted to legacy with the
§9 blend warning); the **stage-and-approve reconcile flow** is the documented path; the
**sync semantics** section carries item 1's `?client=` behaviour, `includeEnded`, and the
real 180s default timeout (was documented as 30s); a **billed-basis table per raw platform
table** (TTD `COSTS` billed / DV360 `REVENUE_ADV_CURRENCY` billed / LinkedIn+Reddit media
= billed / Windsor raw media) with the spendMult rule per row; and the **currency scoping
rule** (no FX in the sync — scope `advertiserValue` to one currency's account).

## Item 8 — autosync design note (design only)

`grid-core/docs/autosync-design.md`: hourly cadence derived from the staleness thresholds;
validated clients only (containment stays `validated: false`); never `includeEnded`;
staleness reframing (once autosync is on, amber = ~5 consecutive failed ticks = pipeline
broken); **loud failure alerting for BOTH credential stores** — tonight's failure mode was
reproduced live during item 6: **ADC is expired** (`RefreshError: Reauthentication is
needed`) while the `bq`/gcloud CLI store still works — auth errors must classify, banner
in the UI, and escalate after 3 consecutive failures, never a quiet `updated: 0`; runtime
pause/resume kill switch on top of `CENTRAL_AUTOSYNC_MIN=0`. **Nothing was enabled.**

---

## For the Mission-1 batch-validation pass — read before the next big sync

1. **Per-client sync is now real.** Validate and first-sync one client at a time:
   `POST /api/central/sync?client=<name>` (+`&includeEnded=1` only when Ended backfills are
   intended). No more all-or-nothing blast radius — but the **approve click still arms the
   no-param sync** for everyone who presses the button, so prerequisites still land BEFORE
   approval.
2. **Restart the grid server before relying on the fix** — any `node server.js` started
   before 2026-07-23 ~11:00 runs the global-sync code from memory (§1b lesson). The local
   :8787 instance was restarted at phase close.
3. **ADC is currently expired on this machine.** `gcloud auth application-default login`
   is needed before `/api/exec` refresh or any `google-cloud-storage`/`google-cloud-bigquery`
   Python path works locally. The `bq` CLI (and `gcloud storage`) credential store is fine
   — the Central sync works today; the Executive local refresh does not.
4. **Cost basis per table is the first check of every validation** (README now carries the
   verified table): TTD `COSTS` and DV360 `REVENUE_ADV_CURRENCY` are CLIENT-BILLED →
   spendMult must be 1 on those rows BEFORE approval; Windsor tables are raw media → the
   sheet-derived mult stays but must be re-verified with the §1 date-bounded check. The
   existing STT/PropTrack/HireRight specs use DV360 `MEDIA_COST_ADVERTISER_CURRENCY`
   (media basis) — each of their runs must pick a basis deliberately.
5. **Currency scoping before anything else on LinkedIn/DV360** (Schneider lesson): the
   sync has no FX. STT is the known danger case — its spec spans SGD + USD accounts on
   BOTH LinkedIn and Google Ads and MUST NOT be validated as-is without resolving the
   currency question.
6. **Sheet Platform Margin cells are not trustworthy** (item 3): two hand-typed artifacts
   survived import sanity checks. Batch-validation should eyeball every TTD/DV360 row's
   platformMargin against the 0.60–0.65 standard before its first sync, and
   `scripts/margin-anomaly-fix.js --apply` awaits sign-off for the two known ones.
7. **The mixed-state UI is now live** (item 4): after each client's first sync, its group
   row should show no `N SHEET` chip (or only deliberately-unmapped rows) — a lingering
   amber chip = an unapproved/unmapped row that will silently never refresh.
8. **A DB rebuild undoes ungoverned prep** (item 2): the EAE spendMult/platformMargin
   writes have no provenance and re-seed to null from `central-import.json`. Any prep
   writes during Mission 1 should go through `db.updateCampaignField` (the
   `margin-anomaly-fix.js` script is the template).
