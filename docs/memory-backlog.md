# Greenlight Memory backlog — proposed issues GL-29..GL-36

> Companion to `memory-design.md` (the ADR). Written in the backlog.md house format so these can
> be lifted into the workbook → `greenlight-issues.json` once the ADR is agreed. Proposed as a new
> milestone **M5 — Greenlight Memory** and epic `epic:greenlight-memory`, sequenced after M4 (M1
> is already at risk for 2026-08-11; nothing here should jump that queue). Owners are suggestions
> only. GL-35 depends on the M2 actuals feed.

## Index

| ID | Title | Type | Priority | Milestone | Est | Owner (suggested) |
|----|-------|------|----------|-----------|-----|-------|
| GL-29 | ADR sign-off: markdown-first memory for Greenlight | documentation | P1 High | M5 | S | Christian |
| GL-30 | Memory store: lesson format, layout, identity index, GCS mirror | feature | P1 High | M5 | M | Ian |
| GL-31 | Deterministic selector + prompt injection with traceable lesson ids | feature | P1 High | M5 | M | Charles |
| GL-32 | Finding feedback: flag control on findings, feedback.json + API | feature | P1 High | M5 | M | Juan |
| GL-33 | Extraction corrections capture on plan values | feature | P2 Medium | M5 | M | Juan |
| GL-34 | Proposal drafting + Memory panel promotion flow | feature | P1 High | M5 | L | Ian |
| GL-35 | Campaign outcome digests into memory | feature | P2 Medium | M5 | M | Jerome |
| GL-36 | Memory regression case + lesson→rulebook graduation discipline | testing | P1 High | M5 | S | Christian |

---

### GL-29 — ADR sign-off: markdown-first memory for Greenlight

`documentation` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **S**

Review and land `docs/memory-design.md`: markdown lesson wiki, deterministic scope selection
(no vector DB), propose→promote human-in-the-loop writes, GL-02-compatible storage split
(client-agnostic lessons in git, client/agency/campaign memory in the data dir + GCS mirror),
documents-beat-memory injection rules, and the lesson→rulebook graduation rule.

#### Acceptance criteria

- [ ] Team has reviewed the ADR; open questions resolved in the doc, not in chat
- [ ] The storage split is confirmed compatible with GL-02's ignore policy
- [ ] The `GREENLIGHT_MEMORY=off|read|propose` flag semantics are agreed
- [ ] Status flipped to ACCEPTED and the doc linked from expected/README.md

**Suggested branch:** `docs/greenlight-memory-adr`

---

### GL-30 — Memory store: lesson format, layout, identity index, GCS mirror

`feature` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **M**

Implement the memory store per the ADR §4–5: `grid-core/expected/memory/` (git, client-agnostic
lessons only) + `GREENLIGHT_MEMORY_DIR` (data dir, gitignored, mirrored with the same best-effort
GCS pattern as store.js). Lesson front-matter parser, status lifecycle
(proposed/active/retired), and `index.json` (job-prefix / filename-pattern → client + agency
slugs). No new npm dependencies — plain fs, hand-rolled front matter, same posture as expected/.

#### Acceptance criteria

- [ ] Lesson files parse (front matter + body); malformed lessons are skipped with a loud log, never crash a run
- [ ] Client/agency/campaign memory lives only under GREENLIGHT_MEMORY_DIR; .gitignore proves it
- [ ] Writes mirror to GCS best-effort and pull down lazily on read (store.js pattern); a mirror failure never breaks a request
- [ ] index.json round-trips: a promotion that names a client/agency updates it
- [ ] memory/README.md documents the format with a worked example

**Suggested branch:** `feat/greenlight-memory-store`

---

### GL-31 — Deterministic selector + prompt injection with traceable lesson ids

`feature` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **M** · depends GL-30

In extract.js: resolve identity (prior run meta → index.json → global-only fallback), select
active lessons most-specific-first under a hard token budget (~3,000, whole lessons only), inject
as the labelled MEMORY block with the three rules (memory never supplies a value; documents win,
contradictions become a watch finding; shaping lessons cited as `lesson:<id>` in the finding
SOURCE tail — no schema change). Record injected ids in `plan.extractor.memory` and results.json.
All behind `GREENLIGHT_MEMORY=read`.

#### Acceptance criteria

- [ ] GREENLIGHT_MEMORY=off (default) is byte-identical to today's behaviour
- [ ] Budget overflow drops whole lessons newest-last with a loud log line
- [ ] Injected lesson ids appear in plan.extractor.memory and the run's results.json
- [ ] First-ever run of an unknown client injects global lessons only, without error
- [ ] Regression gate (memory off) still 13/13

**Suggested branch:** `feat/greenlight-memory-inject`

---

### GL-32 — Finding feedback: flag control on findings, feedback.json + API

`feature` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **M**

Each finding row in the Greenlight tab gets a flag control: false-positive / wrong-severity /
missed-something / useful, plus an optional note. POST
`/analyses/:id/runs/:runId/findings/:findingId/flag` writes `feedback.json` beside results.json
(mirrored like every artifact). Also a run-level "missed finding" entry (something the run should
have caught but didn't — there is no finding row to hang it on).

#### Acceptance criteria

- [ ] Flags persist per run and survive a cold start via the GCS mirror
- [ ] A flagged finding renders its flag state on reload; flags are editable/retractable
- [ ] The run-level "missed finding" free-text path exists
- [ ] Zero auth code added (the Grid's model: platform proxy + Cloud Run IAM)
- [ ] Feedback capture works with GREENLIGHT_MEMORY=off — capture is useful before learning ships

**Suggested branch:** `feat/greenlight-finding-flags`

---

### GL-33 — Extraction corrections capture on plan values

`feature` · `P2 Medium` · `area:grid-core` · `epic:greenlight-memory` · est **M** · depends GL-32

Let a buyer record "this extracted value is wrong; correct is X; because Y" against plan fields
(budget, flight, currency, campaign lines) in the run view. Corrections land in feedback.json with
the field path and the model's original citation. Corrections do NOT rewrite plan.json — the run's
artifacts stay the record of what the model produced; the correction is input to the next lesson.

#### Acceptance criteria

- [ ] Corrections persist with field path, corrected value, reason, author-visible timestamp
- [ ] plan.json and daily_kpi outputs are untouched by a correction
- [ ] The run view shows corrected fields with both values (extracted vs corrected)

**Suggested branch:** `feat/greenlight-corrections`

---

### GL-34 — Proposal drafting + Memory panel promotion flow

`feature` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **L** · depends GL-30, GL-32

Turn captured feedback into lesson proposals in `proposals/` (template for simple flags; one small
model call for corrections/missed findings — violet-tagged AI-authored). A Memory panel in the
Greenlight tab lists proposals and active lessons by scope; a human promotes (proposed→active,
scope editable), retires, or discards. Promotion writes the data dir + mirror; global-scope
promotions are exported as a file the reviewer commits via PR, never written into git by the app.
`GREENLIGHT_MEMORY=propose` gates the drafting call.

#### Acceptance criteria

- [ ] Proposals are inert until promoted (selector never loads status: proposed)
- [ ] Every proposal carries evidence links (analysis, run, finding/correction id)
- [ ] Promote/retire/discard all work from the panel; retired lessons are kept, not deleted
- [ ] Global-scope promotion produces a PR-able file, not a direct git write
- [ ] Proposal drafting cost is visible per proposal (tokens/price), GL-07 style

**Suggested branch:** `feat/greenlight-memory-panel`

---

### GL-35 — Campaign outcome digests into memory

`feature` · `P2 Medium` · `area:grid-core` · `epic:greenlight-memory` · est **M** · depends GL-31; feeds on GL-09..13 (M2)

Per analysis, an outcome digest (`campaigns/<analysisId>/outcomes.md`): how delivery paced vs the
expected baseline, which findings proved real, which were noise. Manual entry in v1; once the M2
actuals join lands, prefill the pacing half from the joined snapshot. Cross-campaign patterns
become lesson proposals through the GL-34 flow (never auto-promoted).

#### Acceptance criteria

- [ ] An outcome digest can be written/edited per analysis and survives cold starts
- [ ] With M2 landed, the pacing summary prefills from the joined snapshot
- [ ] An outcome can spawn a lesson proposal with the digest as evidence

**Suggested branch:** `feat/greenlight-outcomes`

---

### GL-36 — Memory regression case + lesson→rulebook graduation discipline

`testing` · `P1 High` · `area:grid-core` · `epic:greenlight-memory` · est **S** · depends GL-31

The safety net. test_regression.js keeps its cold memory-OFF run untouched; add one memory-ON case
with a planted fixture lesson asserting: injection recorded, the lesson id appears in a finding
SOURCE, and plan.json values are identical to the memory-off run (memory shapes findings, never
values). Document the graduation rule in memory/README.md: a deterministic validation lesson moves
to rulebook.json/validate.js by PR and the lesson is retired pointing at the commit — GL-17/GL-18
retrofit as the worked example.

#### Acceptance criteria

- [ ] Memory-off regression path unchanged and still green
- [ ] Memory-on case: planted lesson injected, cited, and plan values byte-identical to memory-off
- [ ] A poisoned-lesson drill documented: trace a bad finding to its lesson via recorded ids, retire it
- [ ] Graduation rule written down with the GL-17/GL-18 example

**Suggested branch:** `test/greenlight-memory-gate`
