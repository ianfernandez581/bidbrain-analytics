# PHASE 3 REPORT — Schneider onboarding (reconcile + media-plan CONFIG seeding)

**Date:** 2026-07-22 · **Scope:** grid-core, Schneider only · **Playbook:** `grid-core/GRID_BUILD_PLAYBOOK.md` Phase 3

**Status: MATCHES APPROVED (step 2 passed 2026-07-23 — see §9).** The reconcile prep below was
completed and STOPPED at the human-approval gate; the human then approved the **16
high-confidence pairs** in the Map client panel (the 3 medium pairs were deliberately left
unapproved), which wrote the Mode-B map and flipped Schneider `validated: true`. **No sync has
run yet** (`lastSyncedAt` NULL on all 25 rows). Plan ingestion (steps 3-4) and post-sync
verification (step 5) are PENDING; §6-§7 say exactly what is ready for them.

---

## 1. Carry-forward items from the phase prompt — all five resolved or verified

| # | Item (from PHASE3_CLOUDFLARE §9/§10) | Outcome this run |
|---|---|---|
| 1 | `validated: false` containment — don't flip until 2-5 resolved | **Held.** Verified false before starting and after every write; the flip happens ONLY via the human's approve click (which is the required human approval of that write). |
| 2 | Split the Mode-A `pm_delivery` map per platform | **DONE.** Schneider's spec in `central-clients.json` is now **Mode B** (`source: "raw"`, Cloudflare pattern): 3 tables — TTD (`tradedesk_apac_all`, advertiser `Schneider Electric`), LinkedIn (`linkedin_ads_apac`, account `SchneiderElectric_TransmissionSG_AUD`, **group grain**), DV360 (`dv360_apac`, advertiser `APAC \| Schneider Electric AUD`, **insertion-order grain** — see §2). The stale Mode-A map + `bq` block are removed. |
| 3 | All 5 mapped campaignIds stale (DB rebuilt) | **Confirmed + fixed in staging.** The DB was rebuilt 2026-07-22T02:25Z (every campaign's `createdAt`); none of the 5 old ids resolve. All 19 staged pairs carry **current** ids, and the live endpoint verified 19/19 resolve to rows on the correct channel. |
| 4 | TTD spendMult must be 1 before any re-sync | **DONE (instructed write, read-back verified).** All **8** Schneider TradeDesk rows set to `spendMult=1` via the governed `db.updateCampaignField` path (provenance in `central_rows`, source `phase3-schneider-prep`): Airset 2.6629→1, EBA 2.9045→1, Ent IT 2.5001→1, Industrial Edge W3 null→1, LiquidAI 2.5001→1, NEL 2.4984→1, EcoStruxure 3.0373→1, Water&Env 2.5694→1. Script: `grid-core/scripts/schneider-phase3-prep.js` (kept for audit; prints ALL CLEAN only when every read-back matches — it did). Note: a future DB rebuild re-seeds from `central-import.json`, which still carries the sheet mults — re-run the prep script after any rebuild. |
| 5 | The three `Software First EcoStruxure · Linkedin` rows need their Objectives; do NOT archive | **Already resolved at the source — verified, nothing written.** The 2026-07-22 rebuild re-imported from the newer `central-import.json`, which carries the three distinct rows: Awareness ($10,200, ends 09-30), Retargeting 1 ($2,500, ends 09-30), Consideration ($13,000, ends 10-31). The prep script asserts this and would have failed loudly otherwise. None archived. |

Also honored: **no sync was run at any point this session** (the `?client=` bug §10.6 makes any
sync global; Cloudflare is `validated: true` and healthy, but nothing needed a sync). The only DB
writes are the 8 spendMult fields in item 4.

## 2. Reconcile prep — what is staged and why

`grid-core/config/reconcile-staged/Schneider.json` — 19 pairs (16 high / 3 medium), 5 warnings,
6 unmatchable rows, 4 BQ-orphan notes. Rendered first (unticked) in the Map client panel; the
human ticks + approves through the unchanged `/approve` route.

### Match rate

Grid has **25 Schneider rows**; every one is accounted for:

| Outcome | Rows | Detail |
|---|---|---|
| Staged high-confidence | 16 | 8 TTD (Airset, EBA, Ent IT, Industrial Edge W3, LiquidAI, NEL, SF EcoStruxure, Water&Env) + 8 LinkedIn (Advancing Energy T, Airset, Ent IT, Industrial Edge W3, LiquidAI, NEL, SF EcoStruxure **Awareness**, Water&Env) |
| Staged medium (flagged, human decides) | 3 | IA Services · LinkedIn (BQ $8,226 vs sheet $4,955 — does not reconcile), EAE Consideration + EAE Conversion · DV360 (membership certain, but Ended + needs spendMult/platformMargin set — see below) |
| Unmatchable — no BQ data (said plainly, NOT cross-matched) | 4 | Advancing Energy T · **Google Ads** (no Schneider account in `google_ads_apac` — verified STT-only; DTS layer is 100% Digital only), DOOH · DOOH (no DOOH source anywhere), SF EcoStruxure **Retargeting 1** + **Consideration** · LinkedIn (campaigns not launched yet — the sheet itself says "no instructions for setup yet") |
| Needs config before mappable | 2 | Heavy Industries ×2 — both rows have **channel NULL** (two identical placeholder rows in the source sheet, job 2281), but real TTD delivery exists since 07-15 ($179). Human: set channel=TradeDesk on ONE row, then map `contains "Heavy Industries_AWR"`; decide what the twin is for (do NOT auto-archive — §6.1 precedent). |

**Every one of the 84 fetched BQ names is accounted for**: 64 claimed by the 19 rules
(mechanically verified — every rule matches exactly its previewed name count, zero
double-claims), 20 unclaimed and all explained (Heavy TTD + EcoConsult orphan + 7 LinkedIn
2025-history groups + 11 DV360 2025-history IOs).

### The three decisive discoveries (next clients inherit all)

1. **LinkedIn currency lives in the ACCOUNT, and the sync has no FX.** Schneider LinkedIn spans
   three accounts (`SchneiderElectric_TransmissionSG_AUD/_USD/_SGD`; the dashboard's
   `stg_linkedin` converts by suffix ×1.50/×1.15). The Grid sync sums raw `COSTS` with no
   conversion — mixing accounts would write USD/SGD numbers into an AUD grid. Verified: **every
   Grid-relevant group lives in the `_AUD` account** (the `_USD`/`_SGD` accounts hold only
   pre-2026 programs with no Grid rows), so the spec fetches the AUD account ONLY. **Rule for
   every future multi-account client: check the account/currency dimension before staging — if
   in-scope campaigns span currencies, stop and flag (the sync cannot handle it).**
2. **DV360 splits at INSERTION ORDER, not campaign.** The two EAE Grid rows share ONE DV360
   campaign, but the IOs split them exactly: `1974_SE_ANZ_EAE_Consideration_AU+NZ` billed
   (`REVENUE_ADV_CURRENCY`) = **$5,713.90 vs the row's $5,714 budget — to the dollar**, flight
   dates equal to the row's (03-04..06-08). The spec's `campaignColumn` is simply set to
   `INSERTION_ORDER_NAME` (Cloudflare lesson 1 generalizes: pick the grain where totals agree —
   this is the third grain in three clients: campaign, group, insertion order).
3. **TTD mid-flight rename confirmed as a pattern, with a twist worth knowing:** on
   **2026-07-06 every live Schneider campaign** (TTD names AND LinkedIn group names) gained a
   numeric job prefix (`2079_`, `2306_`, `2223_`, `2305_`, `1958_`, `2053_`, `2226_`, `2463_`,
   `2061_`) — a portfolio-wide rename, not per-campaign drift. `contains` rules on the stable
   suffix token span both vintages; the prefixes double as brief-number evidence (e.g. `2305_`
   matches the EcoStruxure row's jobNumber).

### Cost-basis verification (lesson 4 applied)

- **TTD `COSTS` = CLIENT-BILLED, re-confirmed on all 7 spending TTD rows** (not just Airset):
  date-bounded to the sheet vintage (≤07-08), BQ sums sit within 2-6% of the sheet's *billed*
  clientSpend on every row (e.g. Ent IT $21,090 vs $20,636; LiquidAI $11,193 vs $10,913; EBA
  $8,847 vs $8,597) — and nowhere near the media-cost column. Hence spendMult=1 (§1 item 4).
- **LinkedIn `COSTS` = media = billed (mult 1)** — same agreement pattern on all LinkedIn rows
  (e.g. Ent IT $18,379 vs $17,415; W&E $2,483 vs $2,421).
- **DV360 `REVENUE_ADV_CURRENCY` = billed** (the dashboard's own definition of what SE pays) —
  chosen as the costColumn so DV360 behaves exactly like TTD under the spendMult=1 rule. NOTE
  for the human: the existing STT/PropTrack/HireRight specs use `MEDIA_COST_ADVERTISER_CURRENCY`
  instead — their Phase 3 runs must make the same basis decision deliberately.
- **Old pm_delivery blend totals reconcile exactly** with the new per-platform split (NEL $2,145
  TTD + $8,209 LinkedIn; W&E $2,536 + $2,952; Airset $4,721 + $2,376; AET $2,741 LinkedIn-only;
  EBA $12,017 TTD-only) — §6.3's numbers, now landing on the right rows.

### Flagged items awaiting the human's judgment (not forced)

- **IA Services · LinkedIn (medium):** 2 groups sum $8,226 vs sheet $4,955 clientSpent / $5,425
  budget. Which part of the BQ delivery the sheet row covers is not provable. Ended row — a
  backfill (needs `includeEnded=1`) would roughly double its recorded spend. Approve only if BQ
  is accepted as truth; else skip.
- **EAE ×2 · DV360 (medium):** membership is certain (budget-to-the-dollar + exact flight), but
  approving requires the human to also set `spendMult=1` **and** `platformMargin` on both rows
  (currently null — DV360 is a Platform-Margin channel; profit-at-risk falls back to est. 0.60
  until set), and to run the one-time `includeEnded=1` backfill. EAE Conversion's sheet
  clientSpent ($1,804) sits 47% below the billed figure — sanity-check which figure the agency
  wants recorded.
- **Heavy Industries + EcoConsult:** see the match-rate table / orphans. EcoConsult (brief 2279,
  LinkedIn, launched 07-21, $196) has **no Grid row** — recommend adding one.

### ⚠ The approve click IS the re-arm

The approve route flips `validated: true` the moment ≥1 pair is written — and the sync route
still ignores `?client=` (§10.6, unfixed), so the next sync anyone runs anywhere will include
Schneider. That is now SAFE by prep (Mode B map, fresh ids, spendMult=1), but the human should
approve knowing that consequence. This is stated as warning #1 in the staged file, rendered at
the top of the panel.

## 3. Standing-rule compliance check

- **Reader auto-write path:** re-verified NONE exists (not trusted from the prior report):
  `plan-reader.js` header "NEVER writes a campaign row"; the only field-write routes are the
  inline-edit (scope `edit`) and plan-commit (scope `plan`) whitelisted paths, both
  human-triggered. Nothing to disable.
- **Media-plan extractions:** none performed yet (step 3 is after the approval gate). The staged
  reconcile file writes nothing by existing.
- **Reconcile writes:** only the human-triggered `/approve` writes; verified live that a
  platform-crossing pair is rejected 400 with config unchanged (§5).
- **Margin rule:** `calc.js` untouched (frozen). TTD rows all carry platformMargin (0.6-0.97);
  the DV360 gap on EAE is flagged, not silently defaulted.
- **spendMult + objective writes (§1 items 4-5)** were explicit phase-prompt instructions, not
  extractions — executed through the governed CONFIG path with provenance + read-back, on a
  client that cannot sync (`validated: false`).

## 4. Files changed this run

- `grid-core/config/central-clients.json` — Schneider spec: Mode A → **Mode B** (3 tables, notes
  incl. billed-basis + AUD-account-only + IO-grain rationale); stale 5-entry map REMOVED; `map: []`;
  `validated` stays **false**. Top-level `_comment` rewritten (was duplicated + stale: still
  described Schneider as the validated Mode-A example; now documents the Mode-A blend warning +
  the `?client=` sync bug).
- `grid-core/config/reconcile-staged/Schneider.json` — NEW: 19 staged pairs + 5 warnings +
  6 unmatchable + 4 orphan notes (second use of the staged-reconcile pattern).
- `grid-core/scripts/schneider-phase3-prep.js` — NEW (kept for audit): the 8 spendMult writes +
  EcoStruxure objective assertion + post-checks.
- `data/brain-historical.db` — 8 `spendMult` CONFIG fields (+ provenance rows in `central_rows`).
  No metrics, no other clients, no other fields.
- `PHASE3_SCHNEIDER_REPORT.md` — this file.
- **Not changed:** `calc.js`, `server.js`, `match.js`, the sync path, the approve route, the plan
  reader, any dashboard, any Cloudflare artifact.

## 5. Verification (all against live systems, not transcribed)

- `central_sync.py --names Schneider` against the new Mode B spec: **84 names** (32 Trade Desk ·
  37 LinkedIn · 15 DV360), no fetcher errors.
- **Rule partition audit (mechanical):** each of the 19 staged rules matches exactly its
  previewed BQ-name count; **zero names claimed by two rules**; all 20 unclaimed names explained.
- **Fresh server** (dedicated port, started + killed this session — heeding the stale-process
  lesson): `GET /api/central/reconcile/Schneider` serves the staged block (19 pairs / 5 warnings /
  6 unmatchable / 4 orphans); 84 generic suggestions with **0 platform crossings** (incl.
  runner-ups); flags 26 clean / 56 weak / 2 ambiguous; **19/19 staged campaignIds resolve to live
  rows on the correct channel**.
- **Approve guard:** POSTing the NEL LinkedIn token against the NEL TradeDesk row returned
  `400 "platform mismatch … nothing was written"`; config read back unchanged
  (`validated=false, map=[]`).
- Prep script: ALL CLEAN (every write read back; 25 rows still `metricsSource=sheet-import`,
  `lastSyncedAt=NULL`).

## 6. PENDING — plan ingestion (steps 3-4, after match approval)

**Plans are LOCATED — most rows are coverable without asking for files.** Unlike Cloudflare
(where plans had to be provided by hand), Schneider's plans exist in two places:

- **In-repo PDFs** (`clients/client_schneider/raw_files/`): Water & Environment (1130),
  NEL (2053), Advancing Energy Technology (2061 r1), Airset (2223), EcoStruxure Building (EBA),
  Heavy Industries.
- **Google Drive XLSX** (one folder, better for the reader — native SheetJS parse; several
  duplicate the PDFs): Ent IT (`SE 1958 Enterprise IT Expansion Program Media Plan 070426`),
  Industrial Edge W3 (`2463 Final media plan - SEE Industrial Edge Wave 3`), LiquidAI
  (`SE AI and Liquid Cooling Awareness Media Plan 090426`), Software First EcoStruxure
  (`2305_SE Software First EcoStruxure IT CIO & IT Channel Campaign`), IA Services
  (`SE AI Services - Media plan - 200226`), EcoConsult (`SE EcoConsult Media Plan 080426`),
  plus Water&Env / EBA / Heavy / NEL / AET / Airset XLSX twins.
- **Not located** (title search): **EAE (1974)** and any **DOOH** plan — ask the human if those
  two matter (EAE is Ended with full sheet config; DOOH is Not Active with no budget).

**Carry-forward from Cloudflare §10.2 applies verbatim:** the sheet/DB already carries KPI,
forecast CPM, platform margin, objective and dates for the 25 rows, and plans state the
media-budget basis while Central holds client-billed — so step 3 should be a **staged diff for
gap-filling** (the known gaps: EAE platformMargin/objective, IA Services objective, DOOH
everything, Heavy Industries everything, Industrial Edge TTD startDate/budgetGross), NOT a bulk
seed of budgets over the billed figures.

## 7. PENDING — post-commit verification (step 5)

After the human approves matches and (if desired) runs the first sync
(`POST /api/central/sync?includeEnded=1` for the Ended backfills — remembering it syncs
Cloudflare too), this section gets: LIVE/BQ marker counts, pacing + profit-at-risk sanity
(expect billed-basis TTD margins to read ~0% — cosmetic, §2), per-channel margin-type check
(TTD+DV360 → Platform Margin; LinkedIn/Google → Campaign Margin), and the Executive card check —
Schneider's KPI object is one of the 7 `#VERIFY` stubs (`config/kpi-objects/schneider.json`,
`"stub": true`); per the Cloudflare precedent its field-path check is expected to defer to
Phase 4's stub-resolution pass, but must be logged either way.

## 8. Lessons the NEXT client run inherits (beyond Cloudflare's §7 list, all still valid)

1. **Check the account/currency dimension before anything else on LinkedIn (and DV360).** The
   sync has no FX; the fix is advertiser-value scoping (only possible when in-scope campaigns
   don't span currencies). Make this the first BQ query of every Phase 3 run.
2. **Three clients, three grains: campaign (TTD), campaign GROUP (LinkedIn), INSERTION ORDER
   (DV360).** The spec's `campaignColumn` expresses all three — always ask "at what grain do
   sheet and BQ totals agree" per table, not per client.
3. **A DB rebuild both breaks and fixes things** — it invalidated the map ids (again) but also
   delivered the EcoStruxure objective fix through the newer import. After any rebuild: re-check
   what the prompt says is broken before writing "fixes" (item 5 needed zero writes), and re-run
   any DB-level prep (the spendMult reset would be undone by a rebuild).
4. **Watch for portfolio-wide rename events.** Schneider renamed everything on one day
   (2026-07-06). If a client's BQ names all fork on a single date, treat prefixes as vintage
   markers and match on suffix tokens.
5. **When retiring a Mode-A map, delete the old entries in the same change** that stages the
   Mode-B rules — the approve route only APPENDS to `map[]`, so leftovers would revive the blend
   the moment `validated` flips.
6. **The approve click re-arms the sync** (flips validated) — every prerequisite write must land
   BEFORE the human opens the panel, and the staged file's first warning must say so.

## 9. Addendum (2026-07-23) — human approval landed + the durable spendMult fix

**Approval (the human, in the Map client panel):** all **16 high-confidence pairs** approved —
8 Trade Desk + 8 LinkedIn — written to `central-clients.json` `map[]`; Schneider is now
`validated: true`. The **3 medium pairs were NOT approved** (IA Services · LinkedIn, EAE
Consideration + Conversion · DV360) — those rows stay sheet-valued, exactly as the staged
warnings recommended pending their caveats (reconciliation gap / spendMult + platformMargin +
includeEnded prerequisites). They can be approved later from the same panel; the staged file
remains in place.

**Durable spendMult fix (this addendum's one change):** the §1-item-4 DB writes live in the
gitignored SQLite DB — but `config/central-import.json` (which seeds every FRESH DB) still
carried the sheet mults (2.5-3.0). With `validated: true` now committed, a teammate on a fresh
DB clicking Sync would have reproduced the §9 corruption locally. So the **8 Schneider TTD rows
in `central-import.json` were patched to `spendMult: 1`** (read-back verified, 85 rows
preserved). Caveat: if `build_central_import.js` ever regenerates the file from the Central
sheet, this patch is lost — re-apply it (or fix the sheet's Schneider TTD mult cells) after any
regeneration.

**State at push:** map 16/16 platform-clean, `validated: true`, no sync run yet
(`lastSyncedAt` NULL everywhere). Cloudflare untouched.

---

## FOR THE HUMAN — remaining steps

1. ~~Approve matches~~ **DONE 2026-07-23** (16 high; IA Services + EAE ×2 left unapproved — see §9).
2. First sync when ready: the **Sync now** button covers the Active rows (all 16 approved rows
   are Active, so no `includeEnded` needed). It will also re-sync Cloudflare (fine, expected).
3. If you later approve the EAE pairs: first set `spendMult=1` and a `platformMargin` on both
   EAE rows (inline-editable, Margin column group), then backfill once with
   `POST /api/central/sync?includeEnded=1`.
4. Then say the word and the session continues with step 3 (plan ingestion — plans already
   located, §6) and step 5 (post-sync verification, §7).
