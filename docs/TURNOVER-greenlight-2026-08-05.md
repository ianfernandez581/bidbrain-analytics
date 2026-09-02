# TURNOVER — Greenlight session, 2026-08-05

> **For: a fresh Claude on another device, picking this up cold.**
> Read this top to bottom before touching anything. It records what is true, what was verified
> (and how), what is still only designed, and exactly what the next task is. Where something is
> unproven, it says so — do not upgrade a "designed" item to "working" without re-verifying.
>
> Author of session: Christian (christian@100.digital, 100 Digital). Timezone Asia/Manila.

---

## 1. Environment facts

| Thing | Value |
|---|---|
| Repo on disk | `C:\Commissions Folder\BidbrainAI\bidbrain-analytics` |
| Branch | `main` (history is WIP-merge style: "WIP from ian", "Merge lappy/work into integration/merge") |
| The unit in question | `grid-core/expected/` = **Greenlight**, the plan-side / "Expected side" of The Grid |
| Grid UI locally | `http://localhost:8787` (Greenlight tab); standalone plan UI `:8791` |
| Setup script | `grid-core\setup_dev.ps1 -Start` — npm ci, then fetches `ANTHROPIC_API_KEY` |
| Node | v24.14.1 on Windows |
| GCP | project `bidbrain-analytics`, region `australia-southeast1`, service `central-grid` |
| Run cost | ~US$1.40 and 5–7 min per Greenlight run (one `claude-opus-5` call over ~200KB of sheets) |

**Blocker Christian hit:** `setup_dev.ps1` completed `npm ci` (157 packages) but **could not get an API
key** — gcloud is missing/not logged in, so Secret Manager was unreachable. Two fixes: `gcloud auth
login` then re-run, or hand-write `grid-core\.env` with `ANTHROPIC_API_KEY=sk-ant-...`. **Use v2+ of
the `anthropic-api-key` secret — v1 is the old unfunded org key.** As of this session he had NOT
resolved this, and said he may only be able to test in live.

---

## 2. Where Greenlight actually stands

**The prototype works; productionisation has barely started.**

- Against the 28-issue backlog: **~2% moving.** Every issue is `Backlog` except **GL-28** (byte-upload
  path, Charles) marked `In Progress`. Nothing marked Done.
- Against the overall vision: **~40–50%.** The hard part is built — dump in → one cited Claude
  extraction + deterministic validators → out come `plan.json`, `findings.json`,
  `daily_kpi.xlsx/json`, `pacing.html`, `flowchart.html`, `report.md`, `chase_messages.md`.
- **Live status: 0% — `GREENLIGHT_ENABLED` defaults OFF and GL-03 (flip it on: flag, secret, bucket,
  smoke run) is still Backlog.** So "test in live" may not even be possible yet; that is Ian's call.

Milestones: **M1 Hardening due 2026-08-11** (10 issues, 9 untouched incl. both P0s — at risk),
M2 Actual side 08-25, M3 Inputs/checklist 09-08, M4 Rollout.

Two P0s: **GL-01** extraction runs ~320s synchronously inside the HTTP request
(`grid-core/expected/routes.js:89`, `TODO(background-job)`; deploy crutches it with `--timeout 600`)
and **GL-02** purge committed client raw material from git. GL-01 blocks GL-03.

Christian's own M1 items are GL-05 (fix `expected/README.md` drift) and GL-27 (ONBOARDING.md), both XS.

---

## 3. What this session produced (files already on his disk, UNTRACKED in git)

```
docs/memory-design.md      ← ADR: markdown-first memory for Greenlight
docs/memory-backlog.md     ← proposed GL-29..GL-36, house format, new milestone M5
```

**The feature designed:** the AI accumulates experience per campaign and per flagged mistake, stored
as **markdown lesson files** — not a vector DB. Christian researched RAG/vector DBs and deliberately
chose "LLM wiki / markdown-first memory". The ADR argues why that's right *at this scale* (dozens–
hundreds of lessons, retrieval key is already structural: analysis id, 4-digit job prefix, client/
agency), and keeps a documented escape hatch (a vector index can slot in behind the same selector
interface later without changing the lesson format).

Design load-bearing points, do not silently drop them:

1. **Storage splits by sensitivity** because of GL-02: client-agnostic lessons in git under
   `grid-core/expected/memory/`; client/agency/campaign memory in a gitignored
   `$GREENLIGHT_MEMORY_DIR` mirrored to GCS like `store.js` dumps.
2. **Deterministic selection**, most-specific-first: campaign → client → agency → global, under a
   hard ~3,000-token budget, whole lessons only.
3. **Memory never supplies a value.** It shapes attention and findings; every extracted value still
   needs a citation from *that* dump. Documents beat memory; contradiction → a `watch` finding.
   Lesson ids ride the existing `SOURCE` tail as `lesson:<id>` — no schema change needed.
4. **No auto-learning.** Feedback → proposal → **human promotes**. Guards against memory poisoning.
   Injected lesson ids are recorded in `plan.extractor.memory` + `results.json` so a bad lesson is
   traceable and retirable.
5. **Graduation rule:** deterministic lessons move into `rulebook.json`/`validate.js` by PR and the
   lesson retires. Keeps the prompt budget flat forever. GL-17/GL-18 are this pattern done manually.
6. Flag: `GREENLIGHT_MEMORY=off|read|propose`. Ship read path first.

**Status: DESIGNED ONLY. Zero lines of memory code exist.** There is no `memory/` directory, no
selector, no lesson file anywhere in the repo. If Christian asks "where are the memory md files in
live" — the answer is they don't exist yet.

---

## 4. What was VERIFIED about storage (and what wasn't)

Christian asked whether uploads/outputs are actually stored, or only theoretically. **Verified
empirically, 13/13 assertions passed**, against the real `store.js` on his machine — no API key, no
gcloud, no deploy needed, because the storage layer is pure fs code independent of the Claude call.

Confirmed working: uploaded files stored byte-for-byte in the analysis's own dump and **still present
after a run**; `report.md`/`chase_messages.md` archived under `runs/<runId>/out/` and read back
identical via `runArtifact` (the exact function the UI download links call); `filesHash` re-run guard
stable + content-sensitive; two analyses cannot see each other's files; `../../../escape.md` upload
gets flattened into the dump, not escaped; oversize rejected; auto-named analysis adopts
`"<client> <job>"`.

Also confirmed: with an unreachable bucket the mirror logs `[greenlight][gcs] upload failed …` and
`boot sync failed (continuing local-only)` and **the local write still succeeds, nothing throws** —
the "logged loudly, never breaks a request" guarantee holds. Those log lines are what a broken
mirror looks like in Cloud Run logs.

**NOT verified:** that the real `gs://bidbrain-campaign-dumps` mirror works. Needs credentials; it is
exactly GL-03's smoke run. So: local disk persistence proven; GCS durability across Cloud Run cold
starts unproven.

> **⚠️ The probe was written to `/tmp/glt/test_store.js` in the device VM — OUTSIDE the repo, and /tmp
> is ephemeral. It is GONE. It was never committed.** Christian agreed it should become a real test
> at `grid-core/expected/store.test.js` (plain node, ~1s, no deps, no API key, following
> `src/central/calc.test.js`) wired into the `npm test` script — **this was agreed but NOT DONE.**
> Recreating it is a good first task; the storage layer currently has zero test coverage, which is
> why "is the storing working?" had no answer he could check himself. It would also give GL-04's CI
> workflow something real to gate on.

**Correction to earlier confusion worth knowing:** `expected/README.md` line ~138 still says "Upload
zone accepts file metadata only; byte upload … is the next milestone." **That is stale.** Charles's
commit `ce0ade4` (2026-08-05 06:28) *added* `store.js` (360 lines) and `routes.js` (338 lines) — real
byte uploads, per-analysis dumps, run archiving, GCS mirror, and `deploy_grid.ps1` updated to bind
`GREENLIGHT_BUCKET` + the API-key secret. So **GL-28 looks code-complete on main** though the backlog
still says In Progress. Charles should confirm and flip it. Deleting that stale README bullet is part
of GL-05.

---

## 5. THE PENDING TASK — seed memory from the buyers' existing manual flags

### The idea (Christian's words, paraphrased)

The media buyers **already have manual records of what they flagged and which files they flagged it
against**. He wants those converted into markdown **now**, so that even though live has no campaign
history, Greenlight has reference memory ready for the demo. He will re-use these same materials in
the demo, and **expects the audit output to match the flags already recorded in the Excel.**

### The six files he supplied (all .xlsx) — Job 2279, Schneider Electric "EcoConsult"

**These are UPLOADS in the previous session and are NOT on disk anywhere. They must be re-supplied
to work on them.** Ask Christian to re-attach, or locate them on his machine.

**Three are the flag registers** — and they are *already stage-aligned to Greenlight's exact six
stages* (`REQUEST RECEIVED / MEDIA PLAN APPROVED / RAW MATERIALS COMPLETE / CAMPAIGN BUILT / LIVE /
PACING`), laid out as stage-columns × issue-rows:

| File | Sheet | Flags | Per-stage (Req/Plan/Raw/Built/Live/Pacing) |
|---|---|---|---|
| `EcoConsult_2279_Awareness.xlsx` | `Greenlight Issues` | 15 | 1 / 3 / 3 / 3 / 2 / 3 |
| `2279_EcoConsult_Consideratoin.xlsx` | `Real Issues` | 20 (stated) | 2 / 6 / 6 / 3 / 2 / 1 |
| `2279_EcoConsult_Conversion.xlsx` | `Greenlight Issues` | 17 (stated) | 3 / 4 / 6 / 3 / 1 / 0 |

≈**52 flags total.** They carry their own inline tags — `[ESCALATED to <person>]`, `[PENDING
CLIENT]`, `[OPTIMIZATION: …]` — plus footer counts (Consideration: "TOTAL: 20 issues | ESCALATED: 6 |
PENDING CLIENT: 3 | OPTIMIZATIONS: 1"). Named people recur: Sofia, Lauren, Mel, Calvin, Gabby, Jade.
LinkedIn account 517045062, built 31 Jul – 3 Aug 2026, Conversion flight 04 Aug – 30 Nov 2026.

**Three are the source materials the flags refer to:**

- `SE EcoConsult Media Plan 080426  2.xlsx` — 875KB, **14 sheets** (`Media Plan`, `Recommendations`,
  `Assets`, `Ad Requirements Social`, `Ad Requirements SEM`, `Premium Display Investment`, `Deck
  Workings`, `Results`, pivots, Sheet1-3).
- `Transmission_Activation_Form_SE EcoConsult 2279 2.xlsx` — the brief; sheets `Launchpad Template`,
  `Launchpad Example`, `Funnel by Persona by Asset`.
- `TAL  EcoConsult Blue Grey White Zone 1.xlsx` — target account list, **22,645 accounts** across
  Blue (3,979) / Grey (2,944) / White (15,722) zones.

### ⚠️ The expectation that must be corrected — kindly, with their own evidence

Christian expects the audit output to match the Excel flags. **The buyers' own document says it
can't.** The Consideration register ends with:

> "**GREENLIGHT SCORE: 9 of 20 issues (45%) were detectable from the raw files alone** (media plan,
> brief, creatives). The remaining 11 required platform access, client conversation, or build
> experience."

Greenlight reads **files only**. So ~45% is the honest ceiling for parity, and the buyers already
measured it. Flags like "Eng+Ops document ad would not save after 5 attempts, ~45 min lost,
LinkedIn support ticket open" or "audience sized live in-platform across 4 rounds (2,100 → 150,000)"
are **not in any file** — no amount of memory changes that.

**Reframe for the demo, which is a stronger story anyway:** don't promise parity. Show that
Greenlight independently catches the file-detectable ~45% *unaided*, and that the remaining 55% is
precisely what seeded memory contributes as forward-looking watch items on the *next* campaign.
That demonstrates the learning loop rather than pretending the extractor is omniscient. Several
flags are textbook memory lessons — the SharePoint-link-requires-login trap, LinkedIn's A$14.75
daily minimum making a split non-executable, exclusion labels in specs not matching platform
strings ("IT" vs "Information Technology"), LGF locking permanently once an ad goes active,
mandatory-URL-even-with-a-form.

### Doability verdict

**Yes, and the fit is unusually good** — the registers are already in Greenlight's stage vocabulary,
so the conversion is largely mechanical. Recommended shape:

1. **Extract** each register with `openpyxl` (`data_only=True`) → one record per flag:
   `{phase, stage, text, tags[], people[], source_file, sheet, cell}`. Stage comes from the column
   header, and **every lesson keeps its `cell` coordinate as its citation** — matching Greenlight's
   "no citation, no value" ethic.
2. **Classify** each flag: *file-detectable* (could Greenlight have caught it from the materials?)
   vs *experience-only*. This split is the demo narrative and should be a column, reviewed by a
   human — the buyers' 9-of-20 is the calibration reference.
3. **Emit** per the ADR §5 format, front matter + ≤~150-token body, into
   `clients/schneider-electric/lessons/` and `campaigns/2279-ecoconsult/`, plus a
   `agencies/transmission/wiki.md` for standing quirks. `origin: manual`, `status: proposed` — a
   human promotes to `active`, per the no-auto-learning rule. Generalise: strip one-off names/dates,
   keep the transferable rule.
4. **Also write** `campaigns/2279-ecoconsult/outcomes.md` — the pacing/underspend history is right
   there (Persona A spent A$3.28 of A$34/day at CPM A$236, recovered +144% reach after broadening).
5. **Do NOT commit the xlsx or client-identifying lessons to git** (GL-02). Client-scoped lessons
   belong in the data dir. Only genuinely client-agnostic rules earn a git lesson.

Since no memory code exists, these seed files are just markdown until GL-30/GL-31 land. That's
fine — the ADR's read path was sequenced first precisely so hand-written lessons pay off on day one.

---

## 6. Gotchas that will bite you

1. **🔴 The identity guard will silently analyse the WRONG campaign.** `extract.js` partitions a dump
   by 4-digit filename prefix (`^(\d{4})[_\s-]`) and on >1 job keeps only the **majority** job.
   `grid-core/files/` already holds the Schneider **NEL job 2053** dump (~10 prefixed files). Only
   *two* EcoConsult files start with `2279_`; the media plan, TAL and activation form have no leading
   prefix at all. So dropping EcoConsult files into `grid-core/files/` → majority = 2053 → **the
   demo audits NEL, not EcoConsult**, with a blocker finding explaining it. Use a **separate
   analysis** containing only the 2279 files. Consider renaming files to a leading `2279_`.
2. **A run with no uploads falls back to `grid-core/files/`** (dev convenience; that dir is
   dockerignored so deployed images have no prestage). Convenient and dangerous — see #1.
3. **`device_bash` cannot delete files** on his machine (`rm` → Operation not permitted). Write
   scratch work to `/tmp` *outside* the mounted repo, or you'll leave junk you can't remove. Move
   unwanted files into a `_to_delete/` subfolder and tell him.
4. **`/mnt/user-data/uploads/` is read-only** — copy staged files elsewhere before modifying.
5. `expected/README.md` contradicts itself on storage durability (ephemeral-by-design vs GCS mirror).
   That's GL-05. Don't trust either line — trust `store.js`.
6. The regression gate is the only place client numbers live: `test_regression.js`, cold run on the
   NEL dump, must extract job 2053, AUD 35,000 = 8,000 TTD + 6,000/14,000/7,000 LinkedIn, flight
   2026-06-01→2026-08-22 (83 days), and re-catch the 35,000-vs-27,000 label and 82-vs-83-day errors.
   **Last green 2026-08-04, 13/13.** Keep it memory-OFF; add a separate memory-ON case (GL-36).
7. Repo conventions: **no Express** (plain `node:http`), **no new npm deps** in `expected/` (hand-
   rolled front matter, `data_only=True` openpyxl on the Python side), zero auth code in Greenlight
   (the Grid's model: platform proxy + Cloud Run IAM), violet = AI-authored in the UI, and every
   value cites `file | sheet, row`.

---

## 7. Suggested first moves

1. Ask whether he wants the **EcoConsult seed extraction** (§5) or the **`store.test.js` commit**
   (§4) first. Both are self-contained and neither needs an API key.
2. If EcoConsult: get the six xlsx re-attached, then build the extractor + the file-detectable/
   experience-only classification, and **lead with the 45% reframe** before he builds the demo
   around an expectation the buyers' own data contradicts.
3. Nudge him to ask Charles to flip GL-28 to Done, and Ian whether `central-grid` is actually
   deployed with `GREENLIGHT_ENABLED=true` — that single answer decides whether "test in live" is
   even on the table.
