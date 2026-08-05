# ADR: Greenlight Memory — markdown-first learning per campaign and per flagged mistake

> Status: PROPOSED · Author: Christian (drafted with Claude) · Date: 2026-08-05
> Scope: Greenlight only (extract.js prompt + validate.js rulebook). Central/Pulse are out of scope
> for v1; the design leaves a seam for them.

## 1. Context — the problem

Every Greenlight run starts from zero. The extractor is deliberately client-agnostic (nothing in
`extract.js` names a client, a job, or a number), which is right for correctness but means the
system never gets *better*:

- **Known false positives recur on every run.** The UTM required-param checks fire on reference
  URLs, and `referenced_files` name-mismatches flag genuinely-used assets as unreferenced — both
  sit in expected/README.md as "known tuning items" and in the backlog as GL-17/GL-18. Until a
  human changes code, every campaign pays for them again.
- **Corrections evaporate.** When a buyer knows the extracted budget or flight is wrong and why
  (e.g. "Transmission prefixes brief numbers onto campaign names mid-flight" — a lesson the team
  already learned the hard way on LQAIDC), that knowledge lives in someone's head or a Slack
  thread, not in the next run.
- **Outcomes never feed back.** After a flight, we know which findings mattered and which were
  noise. Nothing routes that signal into future runs.

We want the AI to accumulate experience per campaign and per flagged mistake.

## 2. Decision — markdown-first memory, not a vector database

Memory is a **wiki of small, curated markdown lesson files**, selected **deterministically by
scope** (global → agency → client → campaign), injected into the one extraction call as a clearly
labelled context block, and written back through a **human-reviewed** propose→promote flow.

No embeddings, no vector store, no similarity search.

**Why this beats RAG-with-a-vector-DB here:**

1. **Scale.** The corpus is dozens-to-hundreds of lessons, not millions of chunks. Semantic
   retrieval earns its keep around 10k+ items; below that, exact scoping by client/agency/campaign
   is *more* precise than cosine similarity, not less.
2. **Auditability.** Lessons are diffable, git-reviewable (the global ones), and readable by a
   human in the same breath as `rulebook.json`. A vector DB is a black box in a system whose whole
   brand is "every value cites its source."
3. **The retrieval key is already structural.** We know exactly which memory applies: the analysis
   ID, the 4-digit job prefix, the client/agency from prior runs. There is nothing fuzzy to search.
4. **One less moving part.** store.js already gives us the storage pattern (local FS + best-effort
   GCS mirror). Markdown rides it for free.
5. **Reversible.** If the corpus ever outgrows this, a vector index can be added *behind the same
   selector interface* without changing the lesson format. Markdown-first is not markdown-only.

## 3. The four learning inputs and what each becomes

| Input | Captured where | Becomes |
|---|---|---|
| **Flagged finding** (false positive / wrong severity / missed / confirmed useful) | flag control on each finding in the Greenlight tab → `feedback.json` on the run | a **lesson proposal** (extraction- or validation-scoped) |
| **Extraction correction** (buyer says "this value is wrong, correct is X, because…") | correction control on plan fields in the run view | a **lesson proposal**, usually agency- or client-scoped (format quirks) |
| **Campaign outcome** (what paced, which findings mattered) | post-flight digest per analysis (manual in v1; fed by the M2 actuals join later) | `outcomes.md` on the campaign + cross-campaign lesson proposals |
| **Client/agency quirk** (stable facts: naming conventions, billing currency, sign-off habits) | promoted lessons + a per-client/agency `wiki.md` | standing context injected whenever that client/agency's files show up |

## 4. Storage layout — and the GL-02 constraint

**Client material must never be committed to git** (GL-02 is purging exactly that today). So memory
splits by sensitivity, mirroring the rulebook's own note that "per-client facts never live here":

```
grid-core/expected/memory/            ← IN GIT (client-agnostic only, PR-reviewed)
  README.md                              format spec + curation rules
  lessons/extraction/*.md                e.g. "setup-sheet TOTAL rows often include paused lines"
  lessons/validation/*.md                incubating rulebook changes (see §8)

$GREENLIGHT_MEMORY_DIR/               ← DATA DIR (default expected/memory-data/, gitignored;
  index.json                             GCS-mirrored like store.js dumps — survives cold starts)
  agencies/<slug>/wiki.md
  agencies/<slug>/lessons/*.md
  clients/<slug>/wiki.md
  clients/<slug>/lessons/*.md
  campaigns/<analysisId>/notes.md
  campaigns/<analysisId>/outcomes.md
  proposals/<id>.md                      staged lessons awaiting human promotion
```

`index.json` is the identity map the selector uses: job prefixes and filename patterns → client and
agency slugs (e.g. `2053 → {client: schneider, agency: transmission}`). It is maintained as a side
effect of promotion, never guessed at run time.

## 5. Lesson format

One lesson = one file = one transferable observation. Front matter + short body, hard-capped
(~150 tokens of body) so the injection budget stays predictable:

```markdown
---
id: agency-transmission-0007
scope: agency/transmission          # global | agency/<slug> | client/<slug> | campaign/<analysisId>
kind: extraction                    # extraction | validation | outcome
status: active                      # proposed | active | retired
origin: flag                        # flag | correction | outcome | manual
evidence: analysis a3f2c1, run 9b41d2, finding m_label   # where this was learned
created: 2026-08-05
---
Transmission renames campaigns mid-flight by prefixing the 4-digit brief number
(e.g. "SE_LQAIDC_*" became "2306_SE_LQAIDC_*" in July 2026). When setup-sheet
names and plan names disagree only by a leading `NNNN_`, treat them as the same
campaign line; do not emit a scope-change finding for the rename alone.
```

The wiki.md pages are the same idea at page grain: standing facts about a client/agency, curated by
hand, budget-capped the same way.

## 6. Retrieval — deterministic selection, no search

At run start (in `extract.js main()`, after `preprocess()`):

1. Resolve identity: analysis ID → prior run's `results.json` `meta.client` (most campaigns are
   re-run many times), else `index.json` match on the dump's 4-digit job prefixes / filename
   patterns. **A first-ever run of an unknown client gets global lessons only — that is correct,
   not a failure.**
2. Collect `status: active` lessons, most-specific first: campaign → client → agency → global.
3. Apply the token budget (start at ~3,000 tokens total, newest first within a scope; drop
   whole lessons, never truncate one mid-body).
4. Record what was injected: the selected lesson IDs go into `plan.extractor.memory` and the run's
   `results.json`, so any finding can be traced back to the lesson that shaped it — and a bad
   lesson can be found and retired.

This is ~100 lines of plain fs code, same dependency posture as the rest of expected/ (no new
packages).

## 7. Injection — how memory enters the one Claude call

A second labelled section in the user message, before the bundle:

```
MEMORY — lessons from previous campaigns and flagged mistakes. Rules:
- Memory guides attention. It NEVER supplies a value: every extracted value
  still requires a citation from THIS dump's documents.
- If memory contradicts the documents, the documents win — and emit a watch
  finding noting the contradiction.
- When a lesson shaped a judgement finding, append its id to the finding's
  SOURCE field as "lesson:<id>".

[lesson agency-transmission-0007] Transmission renames campaigns mid-flight...
[lesson global-0003] Setup-sheet TOTAL rows often include paused lines...
```

This preserves the extractor's hard rules untouched: no invented values, missing stays missing,
citations mandatory. Memory makes the model *look in the right places and stop repeating known
mistakes*; it never becomes a source. The `SEVERITY | STAGE | CHIP | TITLE | DETAIL | SOURCE`
pipe format already has a SOURCE tail that can carry `lesson:<id>` without a schema change.

## 8. Write path — propose, then promote (never auto-learn)

The failure mode to design against is **memory poisoning**: one bad flag silently degrading every
future run. So writes are two-phase, matching the repo's "violet = AI-authored, a person reviews
and sends" ethic:

1. **Capture** (cheap, structured): flags and corrections POST to the run
   (`feedback.json` beside `results.json`, mirrored to GCS like everything else).
2. **Propose**: a small model call (or a plain template for simple flags) drafts a lesson file
   into `proposals/` — scope suggested, evidence links filled in. Proposals are inert: the
   selector never loads them.
3. **Promote**: a human reviews in the Memory panel (or just edits the markdown — it's a wiki) and
   flips `status: proposed → active`, adjusting scope if the AI guessed wrong. Promotion of a
   global lesson = a git PR; promotion of client/agency/campaign lessons = a data-dir write +
   mirror.
4. **Retire**: lessons carry their evidence trail; when one misfires (traced via the injected-ids
   record from §6.4), set `status: retired` — never delete, the history is the experience.

**Graduation rule — memory is the incubator, code is the destination.** When a validation lesson
turns out to be deterministic ("UTM checks should not fire on SharePoint reference URLs"), it
graduates: becomes a `rulebook.json` parameter or a `validate.js` change via normal PR, and the
lesson is retired with a pointer to the commit. GL-17 and GL-18 are exactly this pattern done
manually; memory gives every future GL-17 a paved road. This keeps the prompt budget flat over
time instead of growing forever.

## 9. Guardrails

- **Documents beat memory, always** (§7 rule 2). A lesson can never resolve a conflict the
  documents don't resolve themselves.
- **Regression gate runs memory-OFF by default** so the Schneider NEL numbers stay a pure
  extraction test; one added memory-ON case asserts (a) injection happens, (b) a planted lesson's
  id appears in a finding SOURCE, (c) plan values are byte-identical to the memory-off run —
  proving memory changes findings, never values.
- **Token budget is a hard cap** with a loud log line when lessons are dropped for budget.
- **No client material in git** — enforced by layout (§4), same ignore policy GL-02 establishes.
- **Feature-flagged**: `GREENLIGHT_MEMORY=off|read|propose` (off → today's behaviour; read →
  inject only; propose → inject + capture + proposals). Ship read-path and write-path separately.

## 10. What v1 is NOT

Not a vector database (revisit if lessons exceed ~1–2k files). Not automatic learning (a human
promotes every lesson). Not a Central/Pulse feature (the actuals-side cost-basis traps are real
lessons but a different surface — the layout reserves room, nothing more). Not a chat memory —
lessons are per-campaign operational knowledge, not conversation history.

## 11. Sequencing

Read path first (store + selector + injection: GL-29..31), because it delivers value with
hand-written lessons on day one — the team can seed `agencies/transmission/` from what it already
knows. Then capture (GL-32/33), then the proposal/promotion loop (GL-34), then outcomes (GL-35,
naturally after the M2 actuals join). Backlog details in `memory-backlog.md`.
