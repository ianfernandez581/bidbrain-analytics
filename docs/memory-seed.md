# Memory seed — global lessons harvested from buyer-flagged spreadsheets

> Companion to [memory-design.md](memory-design.md). This is the **read-path seed**: hand-curated
> lessons so Greenlight has reference memory on day one, before any campaign has run through it
> and before the capture/promotion UI (GL-32/GL-34) exists.
>
> **Scope of this file: `global` lessons only** — client-agnostic, safe to track in git, same
> policy as `rulebook.json` ("per-client facts never live here"). Agency- and client-scoped
> lessons from the same harvest live in the gitignored data dir, per memory-design.md §4 and GL-02.

## How these were produced

`grid-core/expected/seed_memory.js` walks a folder of media-buyer spreadsheets and extracts every
human annotation deterministically — no model call, no API key, no network — emitting a markdown
ledger per file where every item cites `FILE | SHEET | CELL`. A person then reads the ledgers and
promotes the transferable observations into lessons. The ledgers are regenerable artifacts and are
not tracked; the lessons below are the curated output.

It looks for four things buyers actually do in spreadsheets: **annotation columns** (Remarks /
Status / Go Live / CTA for…, where an *empty* cell is itself a finding), **margin notes** (free text
outside the data block — located by first detecting the table header row, so ordinary data cells are
not mistaken for commentary), **flag phrases** (FLAG, TBC, awaiting, revise, over N char limit, not
provided…), and **review blocks** (The problem / What we propose / What changed / Original / Our update).

First run, against the Schneider NEL 2053 dump already in `grid-core/files` (8 spreadsheets):

| Source file | Annotations | Margin notes | Review blocks | Flag phrases | Unfilled cols |
|---|--:|--:|--:|--:|--:|
| 2053_SE_NEL_LGF_Copy_Review.xlsx | 16 | 0 | 35 | 19 | 0 |
| 2053_SE_NEL_LinkedIn_Creative_Sheet_3.xlsx | 19 | 0 | 0 | 15 | 2 |
| 2053_SE_NEL_LinkedIn_Creative_Sheet_4.xlsx | 10 | 0 | 0 | 4 | 0 |
| 2053_SE_NEL_LinkedIn_Insight_Tag_Implementation.xlsx | 0 | 0 | 0 | 1 | 0 |
| 2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx | 0 | 21 | 0 | 5 | 0 |
| CREATIVE/SE_2053_NEL Content Review Tracker.xlsx | 4 | 1 | 0 | 0 | 3 |
| SE_2053_NEL Content Review Tracker.xlsx | 4 | 1 | 0 | 0 | 3 |
| Transmission_Activation_Form_..._2053.xlsx | 0 | 0 | 2 | 7 | 0 |

**164 flagged items** extracted, then curated into 7 global lessons (below) and 5 scoped ones.

## Usage

```bash
# default: grid-core/files, output to expected/memory-seed/
node expected/seed_memory.js
# point it at the buyers' own flag spreadsheets
node expected/seed_memory.js --files "/path/to/buyer/flag/files" --out /tmp/seed
```

No `ANTHROPIC_API_KEY` required. Reuses the `xlsx` package `preprocess.js` already depends on, so
there is nothing new to install after `npm ci`.

## The global lessons

Each is a standalone file when GL-30 lands (`expected/memory/lessons/global/<id>-<slug>.md`);
they are inlined here for review. Format is memory-design.md §5.

### `global-0001` — linkedin lgf char caps

*kind* `validation` · *status* `active` · *graduation* candidate for rulebook.json (deterministic character counts - see memory/README.md)

**Evidence:** seed from 2053_SE_NEL_LGF_Copy_Review.xlsx | sheet 'LGF Copy Updates' | A2, B8, A20, A34, A44

LinkedIn Lead Gen Forms enforce hard caps that source copy routinely exceeds:
Form Headline 60 chars, Form Details 160 chars, Confirmation CTA button 20
chars, and custom dropdown questions max 15 options. Copy over a cap is not a
typo - it means the built form will differ from the approved copy, so a trim
needs recorded sign-off before activation. When a copy document shows an
original and a shortened version side by side, treat the trim as PENDING
APPROVAL unless an approval record says otherwise.

<details><summary>file: <code>memory/lessons/global/global-0001-linkedin-lgf-char-caps.md</code></summary>

```markdown
---
id: global-0001
scope: global
kind: validation
status: active
origin: manual
evidence: seed from 2053_SE_NEL_LGF_Copy_Review.xlsx | sheet 'LGF Copy Updates' | A2, B8, A20, A34, A44
created: 2026-08-05
graduation: candidate for rulebook.json (deterministic character counts - see memory/README.md)
---
LinkedIn Lead Gen Forms enforce hard caps that source copy routinely exceeds:
Form Headline 60 chars, Form Details 160 chars, Confirmation CTA button 20
chars, and custom dropdown questions max 15 options. Copy over a cap is not a
typo - it means the built form will differ from the approved copy, so a trim
needs recorded sign-off before activation. When a copy document shows an
original and a shortened version side by side, treat the trim as PENDING
APPROVAL unless an approval record says otherwise.
```

</details>

### `global-0002` — launch readiness gates

*kind* `extraction` · *status* `active`

**Evidence:** seed from 2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx | sheet '3. Pillar Targeting Reference' | D5, D34; 2053_SE_NEL_LinkedIn_Insight_Tag_Implementation.xlsx | sheet 'Check It Works' | A2

Setup sheets carry launch-readiness gates in their notes column that no budget
arithmetic will surface. Two recur: a Matched Audience must show as "Ready" in
LinkedIn before launch (uploaded is not ready), and conversion tracking must be
confirmed before launch. Insight Tag verification is a visual check (LinkedIn
Chrome extension: green working, red broken), so a sheet that documents the
method but records no result means the test was described, not performed. Treat
an unrecorded tracking test as a Live-stage gap, not a housekeeping note.

<details><summary>file: <code>memory/lessons/global/global-0002-launch-readiness-gates.md</code></summary>

```markdown
---
id: global-0002
scope: global
kind: extraction
status: active
origin: manual
evidence: seed from 2053_SE_NEL_LinkedIn_Setup_Sheet.xlsx | sheet '3. Pillar Targeting Reference' | D5, D34; 2053_SE_NEL_LinkedIn_Insight_Tag_Implementation.xlsx | sheet 'Check It Works' | A2
created: 2026-08-05
---
Setup sheets carry launch-readiness gates in their notes column that no budget
arithmetic will surface. Two recur: a Matched Audience must show as "Ready" in
LinkedIn before launch (uploaded is not ready), and conversion tracking must be
confirmed before launch. Insight Tag verification is a visual check (LinkedIn
Chrome extension: green working, red broken), so a sheet that documents the
method but records no result means the test was described, not performed. Treat
an unrecorded tracking test as a Live-stage gap, not a housekeeping note.
```

</details>

### `global-0003` — constructed destinations

*kind* `extraction` · *status* `active`

**Evidence:** seed from 2053_SE_NEL_LGF_Copy_Review.xlsx | sheet 'LGF Copy Updates' | A25, B26, A30

Confirmation and thank-you destination URLs are frequently absent from client
source files, so the agency constructs them and proceeds. A document that marks
a URL "CONSTRUCTED", "bypassed", "implied", or "(not provided by ...)" is
recording an unapproved assumption sitting in the live click path. Extract the
URL with its citation AND flag the missing client confirmation - the link works,
which is exactly why nobody notices it was never approved.

<details><summary>file: <code>memory/lessons/global/global-0003-constructed-destinations.md</code></summary>

```markdown
---
id: global-0003
scope: global
kind: extraction
status: active
origin: manual
evidence: seed from 2053_SE_NEL_LGF_Copy_Review.xlsx | sheet 'LGF Copy Updates' | A25, B26, A30
created: 2026-08-05
---
Confirmation and thank-you destination URLs are frequently absent from client
source files, so the agency constructs them and proceeds. A document that marks
a URL "CONSTRUCTED", "bypassed", "implied", or "(not provided by ...)" is
recording an unapproved assumption sitting in the live click path. Extract the
URL with its citation AND flag the missing client confirmation - the link works,
which is exactly why nobody notices it was never approved.
```

</details>

### `global-0004` — empty tracker columns

*kind* `extraction` · *status* `active`

**Evidence:** seed from SE_2053_NEL Content Review Tracker.xlsx | sheet 'Creative and CTAs' | E1, G1, H1 (8-12 rows blank)

Content review trackers ship with their status columns mostly empty: Go Live
status, Go Live Date and Remarks blank across every asset row. An empty status
column is evidence of nothing recorded, never evidence of approval or go-live.
Extract each such column as an approval record with a null status so it lands as
a MISSING finding per asset scope. A tracker that exists but is unfilled is a
weaker signal than no tracker at all, because it implies someone believed the
step was covered.

<details><summary>file: <code>memory/lessons/global/global-0004-empty-tracker-columns.md</code></summary>

```markdown
---
id: global-0004
scope: global
kind: extraction
status: active
origin: manual
evidence: seed from SE_2053_NEL Content Review Tracker.xlsx | sheet 'Creative and CTAs' | E1, G1, H1 (8-12 rows blank)
created: 2026-08-05
---
Content review trackers ship with their status columns mostly empty: Go Live
status, Go Live Date and Remarks blank across every asset row. An empty status
column is evidence of nothing recorded, never evidence of approval or go-live.
Extract each such column as an approval record with a null status so it lands as
a MISSING finding per asset scope. A tracker that exists but is unfilled is a
weaker signal than no tracker at all, because it implies someone believed the
step was covered.
```

</details>

### `global-0005` — stale plan header

*kind* `extraction` · *status* `active`

**Evidence:** seed from SE_2053_NEL Content Review Tracker.xlsx | sheet 'Media Plan' | R4/R5/R6 vs the correction in C4

A media plan header block can print a superseded flight while staying internally
consistent, which is why arithmetic alone will not catch it: the NEL plan header
read 2026-04-28 to 2026-07-18 over 82 days - correct for the dead April flight -
against an agreed June-August flight of 83 days. The only trace of the revision
was a buyer's note in the adjacent cell ("revise to june start through august").
Always read the cells beside and below date and budget rows: an unstructured
margin note is often the newest fact in the document. It resolves nothing on its
own, but it tells you which printed value to distrust.

<details><summary>file: <code>memory/lessons/global/global-0005-stale-plan-header.md</code></summary>

```markdown
---
id: global-0005
scope: global
kind: extraction
status: active
origin: manual
evidence: seed from SE_2053_NEL Content Review Tracker.xlsx | sheet 'Media Plan' | R4/R5/R6 vs the correction in C4
created: 2026-08-05
---
A media plan header block can print a superseded flight while staying internally
consistent, which is why arithmetic alone will not catch it: the NEL plan header
read 2026-04-28 to 2026-07-18 over 82 days - correct for the dead April flight -
against an agreed June-August flight of 83 days. The only trace of the revision
was a buyer's note in the adjacent cell ("revise to june start through august").
Always read the cells beside and below date and budget rows: an unstructured
margin note is often the newest fact in the document. It resolves nothing on its
own, but it tells you which printed value to distrust.
```

</details>

### `global-0006` — unanswered brief propagates

*kind* `extraction` · *status* `active`

**Evidence:** NEL 2053 - unanswered brief (Launchpad Template C37/C38, privacy policy + opt-in) surfacing later as constructed values in 2053_SE_NEL_LGF_Copy_Review.xlsx | A25, B26

An unanswered brief section does not stay a gap - it reappears as an invented
value two or three documents later. On the NEL job the brief left privacy policy
and opt-in consent text blank while the campaign ran five LinkedIn Lead Gen
Forms, so by the copy-review stage the agency had constructed the confirmation
URLs and was awaiting CTA text. When a downstream document marks a value
CONSTRUCTED, assumed or bypassed, check the brief for the question that was never
answered and report them as one chain, not two unrelated findings. The brief gap
is the cause and carries the client action; the constructed value is the symptom.

<details><summary>file: <code>memory/lessons/global/global-0006-unanswered-brief-propagates.md</code></summary>

```markdown
---
id: global-0006
scope: global
kind: extraction
status: active
origin: manual
evidence: NEL 2053 - unanswered brief (Launchpad Template C37/C38, privacy policy + opt-in) surfacing later as constructed values in 2053_SE_NEL_LGF_Copy_Review.xlsx | A25, B26
created: 2026-08-05
---
An unanswered brief section does not stay a gap - it reappears as an invented
value two or three documents later. On the NEL job the brief left privacy policy
and opt-in consent text blank while the campaign ran five LinkedIn Lead Gen
Forms, so by the copy-review stage the agency had constructed the confirmation
URLs and was awaiting CTA text. When a downstream document marks a value
CONSTRUCTED, assumed or bypassed, check the brief for the question that was never
answered and report them as one chain, not two unrelated findings. The brief gap
is the cause and carries the client action; the constructed value is the symptom.
```

</details>

### `global-0007` — brief vs plan gaps

*kind* `extraction` · *status* `active`

**Evidence:** NEL 2053 - Launchpad Template C21 "$30K AUD" and C15 "Qualified leads and enquiries" against a media plan of 35,000 buying impressions on CPM

The brief's commercial asks and the media plan's contract routinely disagree, and
the brief is where to look for both classic gaps: the stated budget (NEL brief
"$30K AUD" against a $35,000 plan) and the KPI framing (brief wants qualified
leads; every plan line buys impressions on CPM). Neither is arithmetic - the plan
is internally consistent in both cases. Extract the brief's budget and primary
KPI verbatim with citations so the comparison is available, and flag the mismatch
as a Request Received gap. Also check whether the brief's budget is stated
including or excluding fees; on NEL that was never stated anywhere.

<details><summary>file: <code>memory/lessons/global/global-0007-brief-vs-plan-gaps.md</code></summary>

```markdown
---
id: global-0007
scope: global
kind: extraction
status: active
origin: manual
evidence: NEL 2053 - Launchpad Template C21 "$30K AUD" and C15 "Qualified leads and enquiries" against a media plan of 35,000 buying impressions on CPM
created: 2026-08-05
---
The brief's commercial asks and the media plan's contract routinely disagree, and
the brief is where to look for both classic gaps: the stated budget (NEL brief
"$30K AUD" against a $35,000 plan) and the KPI framing (brief wants qualified
leads; every plan line buys impressions on CPM). Neither is arithmetic - the plan
is internally consistent in both cases. Extract the brief's budget and primary
KPI verbatim with citations so the comparison is available, and flag the mismatch
as a Request Received gap. Also check whether the brief's budget is stated
including or excluding fees; on NEL that was never stated anywhere.
```

</details>

## Graduation candidates (lesson → code)

Per memory-design.md §8, a deterministic lesson belongs in code, not in the prompt budget.
`global-0001` is the clearest first case: the LinkedIn Lead Gen Form caps are countable, so they
should become `rulebook.json` parameters checked in `validate.js` — the same shape as the existing
`platform_minimums.linkedin_min_daily_budget`. Suggested patch:

```json
"platform_minimums": {
  "linkedin_min_daily_budget": 10,
  "linkedin_lgf_headline_max_chars": 60,
  "linkedin_lgf_details_max_chars": 160,
  "linkedin_lgf_cta_button_max_chars": 20,
  "linkedin_lgf_dropdown_max_options": 15
}
```

When that lands, `global-0001` is retired with a pointer to the commit and the prompt gets shorter.

