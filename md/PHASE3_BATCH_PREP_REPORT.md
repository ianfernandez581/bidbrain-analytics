# PHASE 3 BATCH PREP REPORT — all remaining clients

**Date:** 2026-07-23 · **Scope:** grid-core, every non-validated client · **Mission:** MISSION 1 — BATCH PHASE 3 PREP
**Status: PREP COMPLETE.** 35 pairs staged across 10 clients (13 high / 22 medium confidence), 12 Grid rows documented unmatchable-by-design, 17 spendMult resets staged. **Every one of the 47 non-validated Grid rows is accounted for: 35 staged pairs + 12 unmatchables = 47.** Nothing was approved, no map was written, `validated` untouched everywhere, zero syncs run (read-only BQ only). All 35 pairs passed a 267-check verification (campaignIds resolve in the DB with the right client+channel, every scope exists in the spec, zero double-claims, zero unflagged platform crossings, rollup/empty-value rule semantics proven against the real `match.js`).

**Session note:** the original Mission-1 session completed ALL BQ inventory + per-client pulls but crashed before writing anything (cygwin fork exhaustion from parallel `bq` calls). This session recovered every query result from the crashed session's transcript, re-ran only the 5 queries whose results were lost mid-crash (Ad Assembly/ResetData Meta names, HireRight TTD/LinkedIn/DV360, MongoDB perf_linkedin check, flight-scoped TTD slices), and re-ran them **sequentially via PowerShell** — future sessions should never fire parallel `bq` calls through Git Bash.

---

## STEP 0 — BQ source inventory (written to `grid-core/config/bq-source-inventory.json`)

| Platform | Verdict |
|---|---|
| **Meta** | NO Snowflake table. Windsor `perf_meta` only: Cityperfume.com.au, Ad Assembly ACRS + BuyerX, `Reset backup – Ad account` (EN-DASH), 100% Digital - Clients (Geocon). **Gateway + QTopia Meta = unmatchable by design.** |
| **Reddit** | Cloudflare only, in BOTH sources. **ResetData Reddit = unmatchable.** (See the data bug below.) |
| **Trade Desk** | TWO sources: Snowflake `tradedesk_apac_all` (Transmission seat: Cloudflare/HireRight/MongoDB/**PopTrack**/Schneider) + Windsor `perf_the_trade_desk` (100% Digital seat: City Perfume/ResetData/QTopia/TLM/VMCH/ACRS/Altech/WEHI + orphans). `central_sync.py` handles both via per-table specs. |
| **DV360** | Snowflake only, Transmission clients only. **VMCH ×3 + Bell Shakespeare ×3 DV360 rows = unmatchable.** |
| **LinkedIn** | Snowflake `linkedin_ads_apac` (STT SGD / HireRight USD / PropTrack AUD / Schneider / Cloudflare / Canon). Windsor `perf_linkedin` has **ZERO MongoDB rows** (account 502299829 connector 500s) → **MongoDB LinkedIn = unmatchable until re-auth.** |
| **Google Ads** | Snowflake = STT-only (verified). DTS bridge `raw_google_ads.perf_google_ads` = City Perfume / Reset Data / TLM (+Liberty/Paradise, no Grid rows). The `raw_windsor.perf_google_ads` copy is stale (ends 06-05) — specs repointed to the DTS bridge. |
| **DOOH / LINE** | No source. PropTrack's COBA DOOH row has a plausible TTD display campaign — staged as a flagged crossing. |

**The batch's biggest basis finding — Windsor TTD is CLIENT-BILLED, not raw media** (corrects the README table, now fixed): City Perfume `cost` $7,500.02 = sheet clientSpend **to the cent**; WEHI $4,113.83 vs $4,113.82; Altech $2,639.98 vs $2,639.88; QTopia billed = budget to the dollar. Windsor Meta + DTS Google are raw media as documented (TLM Google −0.6% vs sheet media). Consequence: **every extreme spendMult the mission flagged (7.15 / 10.09 / 7.76 / 5.10 / 4.79 / 3.47 / 2.86 / 2.03) is a media-basis back-out artifact and is staged to 1.**

---

## Per-client results

| Client | Pairs (high/med) | Unmatchable | Mult resets | Headline |
|---|---|---|---|---|
| **MongoDB** | 2 (2/0) | 1 (LinkedIn) | 2 | DNB IDE: SUM(COSTS) = sheet clientSpend **to the cent** ($16,183.91). 15/15 BQ names claimed. platformMargin 0.70 > standard — eyeball. |
| **STT** | 8 (0/8) | 0 | 1 | **DO NOT VALIDATE — currency landmine.** All sources SGD; sheet internally inconsistent (3 rows = SGD figures exactly, DemandNurture rows ~16% off = AUD-conversion signal). USD/legacy sources removed from spec; LinkedIn grain fixed; DV360 switched to billed. Detective find: the June Google "Always On" row is actually the 2 **AI Readiness** campaigns (0.06% match). |
| **PropTrack** | 3 (2/1) | 0 | 2 | TTD +0.9%, LinkedIn +2.2% vs sheet. **Advertiser misspelling is being fixed upstream mid-flight** (PopTrack→PropTrack, 0-spend rows since 07-22) — pairs use `rollup` to span spellings. COBA DOOH↔TTD crossing flagged medium. |
| **VMCH** | 4 (1/3) | 3 (DV360) | 4 | Retirement Living is the clean whole-flight match. RAC/SAH/Disability are **month-slices of continuous campaigns** — approving writes whole-history (deltas quantified per pair). RAC/SAH platformMargin null. |
| **City Perfume** | 3 (1/2) | 0 | 1 | TTD to-the-cent. **HOLD the Google pair: the CP DTS transfer is STALLED at 06-22** (June under-reads ~$2.6k). Google/Meta rules are June-scoped match-alls (empty value — verified against match.js). |
| **ResetData** | 3 (2/1) | 1 (Reddit) | 1 | All three matched channels flight-scoped 06-01→07-31. Meta account has an EN-DASH in its name. Reddit unmatchable + a data bug (below). |
| **TLM** | 2 (1/1) | 0 | 1 | Cleanest media-basis cross-check of the batch (Google −0.6%). TTD extreme mult 7.757 resolved. |
| **QTopia** | 1 (1/0) | 2 (Meta, Google) | 1 | **The batch acid test:** sheet TTD clientSpend $1,360.55 (10.09-mult artifact) understates billed truth by 85% — BQ $2,519.86 = budget to the dollar. |
| **Ad Assembly** | 6 (2/4) | 0 | 3 | Three spelling traps (Altec→Altech, BIONZ→BOINZ, BOINZ lives in the ACRS account). Altec + WEHI reconcile to the cent. Buyer X flagged **Currency in USD**. One TTD row has NO NAME — name it before approving. All Ended → includeEnded. |
| **HireRight** | 3 (1/2) | 0 | 1 | **ENTIRE CLIENT USD — hold.** LinkedIn grain fixed (the pre-seeded `1802` rule over-claimed the 2025 Awareness program by $10k). DV360 delivery ended 01-30 but the row says Active. Pre-seeded map must be REPLACED (not appended) at approval. |
| **Gateway** | — | 1 row | — | Unmatchable by design: no Meta source (only Meta channel). Stays sheet-valued. |
| **Bell Shakespeare** | — | 3 rows | — | Unmatchable by design: DV360-only client, DV360 source is Transmission-only. All Ended anyway. |
| **Caltex** | — | 1 row | — | Draft row (Star Card TTD, starts 07-06): no Caltex advertiser in either TTD source yet. Re-check when it launches. |
| **Next Smile Australia** | — | 0 rows | — | No Grid rows exist at all (checked the DB). Nothing to prep. |

Staged files: `grid-core/config/reconcile-staged/<Client>.json` ×10 — served automatically by the Map client panel (`GET /api/central/reconcile/:client`). Spec refinements (all on `validated:false` clients only) are annotated in `central-clients.json` per-client notes.

## Spec changes made this run (config only — no DB writes, no map writes)

- **STT**: USD/legacy sources removed (LinkedIn `STTGDC_TransmissionSG_USD`, Google `STT (USD)`, DV360 `APAC | STTelemdia GDC`); LinkedIn → `CAMPAIGN_GROUP_NAME`; DV360 → billed `REVENUE_ADV_CURRENCY` (deliberate pick, evidence in the staged file).
- **PropTrack**: LinkedIn → `CAMPAIGN_GROUP_NAME`; second TTD entry for the corrected `PropTrack` spelling; TTD impressions → `COALESCE(IMPRESSIONS, IMPRESSION)`.
- **MongoDB**: TTD impressions → COALESCE (the old "0 impressions" note was a single-column artifact); the `tradedesk_apac_conversion` pixel entry removed (no cost column, reconcile noise, superseded).
- **City Perfume / ResetData / TLM**: Google entries repointed to the DTS bridge (`raw_google_ads.perf_google_ads`); Google/Meta/TTD entries **flight-scoped** to the Grid's Jun(-Jul) rows (an account's multi-year history must not sum onto a one-month row); ResetData gained its Meta entry, and its dead Reddit entry was removed.
- **Ad Assembly**: TTD entries added for the Altech + WEHI advertisers.
- **HireRight**: LinkedIn → `CAMPAIGN_GROUP_NAME`; DV360 → billed; TTD impressions → COALESCE.
- **grid-core/README.md**: billed-basis table corrected — Windsor TTD is CLIENT-BILLED (verified), Windsor Meta/DTS Google raw media (verified); DV360 note updated for the STT/HireRight basis picks.

## Anything weird (escalations beyond the Grid)

1. **perf_reddit slug mislabel:** the only Reddit rows are Cloudflare's (`Transmission_Cloudflare`, CLOUD_ACQ_* campaigns) yet they carry `client_slug='resetdata'` — and the resetdata **dashboard's** Reddit lane filters on that slug. The dashboard may be presenting Cloudflare Reddit campaigns as ResetData's. Needs a look at `ingest/windsor_data_pull` reddit loader + `clients/client_resetdata`.
2. **City Perfume DTS transfer stalled** at 2026-06-22 (ResetData/TLM DTS run to 07-21) — blocks the CP Google backfill and presumably ages the cityperfume dashboard's Google lane too.
3. **PropTrack advertiser rename in flight** on TTD (PopTrack → PropTrack, 0-spend rows since 07-22). Rollup rules absorb it, but readiness views will show two advertisers.
4. **HireRight DV360 row says Active; delivery ended 2026-01-30.** Status correction needed before/with approval.
5. **STT oddity for the currency investigation:** the sheet's DV360 `mediaSpend` ($27,437.68) almost equals the OLDER campaign's **billed** total ($27,614.55) — the sheet's STT numbers look copy-pasted from mixed sources.
6. **Unassigned BQ advertisers** (no Grid rows anywhere): `Peaches & Cream` TTD ($2,570, July, client unknown), `100% Digital` Cairns TTD+Meta (~$576), Geocon Meta ($11.2k — Geocon is a dashboard client but absent from the Grid).

---

## FOR THE HUMAN — approval runbook

**Before anything:** restart the grid server if it predates 2026-07-23 (the `?client=` sync fix must be in memory), and remember **the approve click arms the no-param sync** — commit each client's spendMult resets BEFORE approving its pairs, or the next global sync anyone clicks writes clientSpend at the sheet-mult multiple.

**Per client, the drill is:** (1) open Map client → the staged list renders first, unticked; (2) run the acid test below against the preview; (3) commit the client's `spendMultResets` (staged in its reconcile-staged file); (4) tick + approve the pairs you accept; (5) first sync scoped: `POST /api/central/sync?client=<name>&includeEnded=1` where flagged.

**Approval order (money-material, clean-first):**

| # | Client | Acid test before ticking | Gotchas |
|---|---|---|---|
| 1 | **MongoDB** | DNB IDE preview must read $16,183.91 — equal to the row's clientSpend to the cent | includeEnded=1; platformMargin 0.70 vs standard |
| 2 | **PropTrack** | Banking ABM TTD preview $13,112.87 (to-07-08 $12,928.87 vs sheet $12,810.54) | Decide the COBA DOOH↔TTD crossing separately |
| 3 | **TLM** | Google to-07-08 $3,018.82 vs sheet $3,036.64 (−0.6%) | Match-all Google rule — confirm the empty value survives the panel |
| 4 | **QTopia** | TTD preview $2,519.86 = budget $2,520 — accept the +85% correction of the sheet's $1,360.55 | includeEnded=1; platformMargin 0.50 |
| 5 | **VMCH** | RL preview $11,992.37; then decide the 3 month-slice rows (deltas in the file) | includeEnded=1; set RAC/SAH platformMargin |
| 6 | **ResetData** | TTD to-07-08 $4,691.48 vs sheet $4,949.84 (−5.2% — eyeball) | Reddit row stays sheet-valued; escalate the slug bug |
| 7 | **Ad Assembly** | WEHI $4,113.83 vs $4,113.82 | Name the null TTD row first; hold Buyer X until currency confirmed; includeEnded=1 |
| 8 | **City Perfume** | TTD $7,500.02 to the cent — approve TTD + Meta; **HOLD Google until DTS backfills past 06-22** | includeEnded=1; platformMargin 0.40 |
| 9 | **STT** | **HOLD ALL** until someone answers: what currency are the Grid's STT rows in? (Evidence table in the staged file) | If SGD-as-is is accepted, everything is ready incl. the AI-Readiness reinterpretation |
| 10 | **HireRight** | **HOLD ALL** until the USD treatment is decided + Zhen fills CONFIG | Replace (not append) the pre-seeded map at approval |

**The one-sync-at-the-end plan (mission default):** approve clients 1–8 → commit their mult resets → ONE global `POST /api/central/sync?includeEnded=1` → verify per client that LIVE/BQ badges show, no lingering SHEET chips on approved rows, and each acid-test number matches its preview. **Safer alternative now available** (Phase 4 fixed `?client=`): sync each client scoped immediately after its approval — smaller blast radius, same end state. Either way, Cloudflare + Schneider ride along on any global sync, which is fine — they are validated and current.

**After approvals:** resolve the deferred Executive KPI stubs for each newly-validated client (PHASE4 item 6 carry-forward), and consider Grid rows for Geocon / Peaches & Cream if they should be tracked at all.
