# BUILD PROMPT — the Bidbrain knowledge base, assistant and feedback loop

Paste this whole file to Claude Code, run from the repo root
(`C:\Users\Ian\Desktop\bidbrain\bidbrain-analytics`). It is the brief, the spec and the
acceptance tests. Read it all before writing code.

---

## 1. What you are building, in one paragraph

A working retrieval system inside the Bidbrain platform (`bidbrain-platform/`, Flask, Cloud Run
service `platform-dash`), so the agency can ask questions and get answers grounded in its own
written record instead of a model's guesses. Five surfaces: a **Documents** library that behaves
like Windows File Explorer, where a file dropped in is searchable within seconds; an **Assistant**
panel with a **knowledge base picker**; a **feedback loop** that turns a buyer's correction into a
new, trusted document any other buyer's answer can then use; an **Observability** page showing what
retrieval actually did; and **usage tracking**. The first user is Charles. The long-term users are
every media buyer.

This exists already, built properly, in another repo. You are porting its design, not inventing one.

---

## 2. The reference implementation — read this before you write anything

`C:\Users\Ian\Desktop\Repositories\Agora\sentinel` is a finished hybrid-RAG system by the same
author. **It is READ-ONLY reference. Never edit it, never import from it, never copy a secret or a
key out of it.** Copy designs and the reasoning in its comments; retype the code to fit Flask.

Read these, in this order, and take exactly what each column says:

| File | Take from it |
|---|---|
| `docs/HOW-SENTINEL-WORKS.md` (§ "The AI Assistant", § Observability, § RAG Visualizer) | What the finished product feels like to a user, and the idea of a self-knowledge document that ships in the prompt |
| `backend/app/models/document.py` | The table shapes: documents, revisions, chunks, origins. Private-by-default reasoning. `indexed_hash` for staleness. `embed_error` so a gap is declarable |
| `backend/app/services/doc_search.py` (whole file, especially the header, `chunk_text`, `_Corpus`, `_IndexCache`, `search`) | The retrieval core: chunk sizes, BM25 + vector fusion by **rank** (RRF k=60), visibility enforced in the retriever, scope vs preference, the multi-instance cache signature, and the span-wraps-every-early-return rule |
| `backend/app/services/embeddings.py` | Vertex `:predict` over stdlib HTTP with the runtime SA token; `RETRIEVAL_DOCUMENT` vs `RETRIEVAL_QUERY`; batching with split-on-refusal; packing vectors as base64; fail soft and say so |
| `backend/app/services/documents.py` + `backend/app/routers/documents.py` | Write path: revision before every change, reindex on every write, upload handling (PDF via pypdf, text, size caps, refusing binary) |
| `backend/app/services/llm_providers.py` | One interface over several model wire formats, SSE streaming over stdlib HTTP, cancellation that closes the socket, explicit User-Agent |
| `backend/app/tracing.py` + `backend/app/routers/observability.py` | Phoenix wiring: OTLP/HTTP is **protobuf only**, the encoder-without-transport trick, no-op when off, never raise into a request, and proxying the Phoenix UI same-origin behind our own auth |
| `frontend/static/js/documents.js` + `frontend/static/css/rag.css` | The Explorer UI: nav tree, breadcrumb address bar, sortable details list, icons view, selection, right-click menus, F2 rename, Delete, drag-onto-folder to move, folders as a path convention over one flat string, "ghost" empty folders |
| `frontend/static/js/rag.js` | How the pipeline is explained to a non-technical reader, and the rule that every claim on that page maps to a named code path |

Also read, in **this** repo, because you are extending them rather than starting fresh:

- `bidbrain-platform/README.md` — the whole thing, especially "Internal Notes + Internal Assistant",
  "How The Brain works explainers", "Layout", "Deploy & operate", "Local dev (no GCP)".
- `bidbrain-platform/dash/main.py` — session kinds, `_admin_kind()`, `_explainers_allowed()`,
  `_internal_allowed()`, the `@app.after_request` no-store rule, how templates are rendered.
- `bidbrain-platform/dash/internal_chat.py` — today's assistant: one Gemini turn over a stuffed
  prompt. **This is what you are replacing with retrieval.** Keep its two hard-won Gemini gotchas.
- `bidbrain-platform/dash/internal_notes.py` — the per-client JSON-in-GCS store. Same storage idiom.
- `md/AGENTS.md` — repo-wide rules. Non-negotiable ones are quoted in §12 below.

---

## 3. Users and access

| Who | Documents | Ask | Feedback | Observability |
|---|---|---|---|---|
| Super admin | full | yes | yes | yes |
| Admin | full | yes | yes | yes |
| 100% Digital agency session (`x100-digital`) | upload + edit own + read all | yes | yes | no |
| Any other agency, any client session | **nothing — 403** | no | no | no |

`KB_AGENCY = "x100-digital"` is the single knob, next to `EXPLAINER_AGENCY` in `main.py`. Follow the
pattern already there: the route is the gate, the template flag only decides what renders. Copy
`_explainers_allowed()`, not `_internal_allowed(client)` — the latter takes a client slug and answers
a different question (may this session open that client's dashboard).

The Documents tab and the Assistant live in **the super-admin console** and **the 100% Digital agency
portal**. Put the Documents entry beside the existing Tools section in the console, and as a tab in
the portal's rail next to The Brain. The Assistant is a panel available on both.

---

## 4. Decisions already made — build these, do not re-litigate

1. **Storage is GCS, not a database.** Everything lives under `kb/` in the existing platform bucket
   (`GCS_BUCKET`, today `bidbrain-analytics-platform-dash`). No Cloud SQL, no new vector database.
   The corpus is thousands of chunks, not millions. Layout in §5.
2. **The index is in memory, rebuilt from GCS, shared by cache signature.** Port Sentinel's
   `_IndexCache`: a cheap manifest read (generation number + counts) decides whether this instance's
   copy is stale. Cloud Run runs several instances; the one that served the upload is not the one
   that serves the next question.
3. **Retrieval is hybrid, fused by rank.** BM25 + cosine, 40 candidates each, RRF `k=60`, at most 2
   chunks per document, 8 passages total. Copy Sentinel's numbers exactly; they are tuned.
4. **Chunks are ~220 words with 40 words of overlap**, split on structure first.
5. **Embeddings: Vertex `text-embedding-005`, `australia-southeast1`**, called with the runtime
   service account's token from the metadata server. `RETRIEVAL_DOCUMENT` when storing,
   `RETRIEVAL_QUERY` when searching. If Vertex is unavailable the answer still happens on BM25 alone
   and **the UI says "keyword only" out loud**.
6. **The model is Kimi.** Secret `kimi-api-key` already exists in this project.
   🔴 The code key only works against `https://api.kimi.com/coding/v1`; pointed at `api.moonshot.ai`
   it returns 401 and looks exactly like a revoked key. Models: `k3`, `kimi-for-coding`. Keep
   Gemini (already mounted as `GEMINI_API_KEY`) as a named fallback when Kimi errors before the
   first token, and say which model answered in the UI.
7. **Numbers come from tools, never from embeddings.** Do not index dashboard figures. If a question
   needs live campaign numbers, the assistant reads the client's `data.json` the way
   `internal_chat.py` already does. Retrieval is for the words: plans, decisions, rules, know-how.
8. **Feedback becomes a document.** The loop is the point of the whole build. Spec in §8.
9. **Original files are kept.** Sentinel discards the file and keeps the text; here a media plan gets
   re-opened by humans, so store both.
10. **Nothing is client-facing.** Staff and 100% Digital only, for now.
11. **Phoenix is optional and off by default.** Everything must work with it off, exactly as Sentinel
    does: no-op spans, and the Observability page explains how to turn it on instead of erroring.
12. **New dependencies are limited to `numpy` and `pypdf`** (plus, in phase 6 only,
    `opentelemetry-sdk` and `opentelemetry-exporter-otlp-proto-common`). No LangChain, no LlamaIndex,
    no vendor SDKs, no vector database client. `requests` is already in the image.

---

## 5. Storage layout

```
gs://<GCS_BUCKET>/kb/
  manifest.json                  {generation, docs, chunks, embedded, updated_at}
  docs/<doc_id>.json             metadata + full text + revisions[]
  chunks/<doc_id>.json           [{ord, text, embedding(base64 float32), model}]
  files/<doc_id>/<filename>      the original upload, byte for byte
  feedback/<fb_id>.json          one record per piece of feedback (§8)
  chats/<user_key>/<conv_id>.json   conversations, private to that user
  activity/<YYYY-MM>.jsonl       append-only usage log (§9)
```

`docs/<doc_id>.json`:

```json
{
  "id": "d_2026…", "title": "…", "folder": "Media plans/Northbourne",
  "kind": "note|plan|brief|meeting|reference|feedback",
  "source": "upload|paste|assistant|feedback",
  "filename": "media-plan-v3.pdf", "mime": "application/pdf", "bytes": 482113,
  "body": "full extracted text",
  "owner": "ian@100.digital", "created_at": "…", "updated_at": "…", "updated_by": "…",
  "indexed_at": "…", "indexed_hash": "sha256 of title+body", "embed_error": "",
  "trust": "verified|standard", "archived": false,
  "revisions": [{"at": "…", "by": "…", "via": "human|assistant", "body": "…"}]
}
```

**Folders are a path convention over one flat string**, exactly as in Sentinel: `Media plans/Q4` is
`Q4` inside `Media plans`. No folder registry. An empty folder exists only in the browser until
something lands in it, and the UI says so.

Seed these folders on first run, empty, with a one-line README document in each explaining what
belongs there: `Media plans/`, `Briefs/`, `Meetings/`, `Platform docs/`, `Playbook/`,
`Media buyer knowledge/`.

---

## 6. The pipeline

```
upload/paste ─► extract text ─► chunk (220/40) ─► embed (Vertex, RETRIEVAL_DOCUMENT)
                                                     └─► kb/chunks/<id>.json ─► manifest++
question ─► embed (RETRIEVAL_QUERY) ─┬─► BM25 over the in-memory corpus ─┐
                                     └─► cosine over the same corpus ────┴─► RRF k=60
        ─► scope filter (picker) ─► top 8 passages ─► prompt ─► Kimi (SSE) ─► answer + citations
                                                                      └─► feedback ─► new document
```

Rules that are easy to get wrong, all of them learned the hard way in Sentinel:

- **Scope filters before scoring, never after.** The knowledge-base picker narrows the candidate set
  going in.
- **Every answer cites.** A passage used is shown with its document title and folder, and clicking it
  opens the document at that passage.
- **Declare the gap.** If embeddings failed, the response carries `semantic: false` and the reason,
  and the panel prints "searched by keyword only".
- **Re-index on every write**, and key staleness on a content hash, not a timestamp.
- **An unreadable file is refused**, never stored as mojibake.
- **The assistant may propose an edit to a document, never perform one silently.** Propose → the
  person approves → it executes in their session, writing a revision.

---

## 7. Build order — ship each phase working before starting the next

Each phase ends with its own check. Do not batch them.

**Phase 1 — store + index (no UI).** `kb_store.py` (GCS read/write/manifest), `kb_chunk.py`,
`kb_embed.py` (Vertex), `kb_index.py` (corpus cache, BM25, cosine, RRF).
*Done when:* a Python REPL can add two documents, search them, and get sensible ranked passages with
`semantic: true`; and a second process sees the new document without a restart.

**Phase 2 — documents API.** `GET /kb/docs`, `POST /kb/docs`, `POST /kb/upload`, `GET/PATCH/DELETE
/kb/docs/<id>`, `POST /kb/docs/<id>/move`, `GET /kb/file/<id>`, `GET /kb/tree`. All gated per §3.
*Done when:* `curl` can upload a PDF and a `.md`, list the tree, move one between folders, and every
gate returns 403 for a client session in the Flask test client.

**Phase 3 — Explorer UI.** `templates/kb_documents.html` + `static/kb.js` + `static/kb.css`, ported
from `documents.js`: nav tree, breadcrumbs, details/icons views, sortable columns, multi-select,
right-click menu, F2 rename, Delete, drag onto folder, drag-and-drop upload onto the file list, an
upload progress row, and a per-row indexing state (`indexing…` → `searchable`).
*Done when:* Charles can drop five files into a folder and see them become searchable without a page
reload.

**Phase 4 — assistant.** `kb_chat.py` (Kimi SSE, Gemini fallback), `kb_prompt.py` (fixed block order:
system rules → self-knowledge doc → retrieved passages with ids → recent turns → question), the panel
UI with: knowledge-base picker (tree of folders with counts, "Entire knowledge base" default,
remembered per browser), streaming answer, stop, citations, model name, and the "keyword only" notice.
*Done when:* a question answers from an uploaded media plan, cites it, and clicking the citation opens
that document.

**Phase 5 — the feedback loop.** §8 in full.
*Done when:* marking an answer wrong with a correction produces a new `Media buyer knowledge`
document, and the same question asked again retrieves that correction above the original source.

**Phase 6 — observability.** Local trace records always; Phoenix when configured. Page shows: Kimi and
Vertex reachability, index size, embedded vs pending counts, a probe box that runs the real retriever
and prints each passage with which retriever found it (keyword / semantic / both), the last 50
questions with their latency and passage count, and the Phoenix UI framed same-origin when set.
*Done when:* the page answers "why did it say that?" for a question asked five minutes earlier.

**Phase 7 — activity + docs.** §9, then the README sections and the explainer updates in §13.

---

## 8. The feedback loop (no Sentinel equivalent — read this closely)

Every answer carries three buttons: **Right**, **Right, not here**, **Wrong**. Choosing any of the
last two opens a one-line correction box. Optional on **Right**.

On submit, write `kb/feedback/<id>.json`: the question, the answer, the verdict, the correction, the
passage ids that were used, who, when, and which model answered.

**Then promote it into the knowledge base.** A feedback record is only useful if the next answer can
find it, so create or update a document in `Media buyer knowledge/` with:

- `kind: "feedback"`, `source: "feedback"`, `trust: "verified"`
- title: a short statement of the rule, written from the correction
- body: the correction, the question that triggered it, and a link back to the passages it corrects

**`trust: "verified"` is a real ranking signal, not a label.** Give verified documents a fixed bonus
in the fused rank, ahead of raw source material, and say so on the Observability page and in the
visualizer. A correction that does not outrank the thing it corrects has not been learned.

Rules:

- A correction is **never** written into the document it corrects. The original stays as it is.
- Feedback is visible to every media buyer. This is shared knowledge, not private notes.
- The assistant must say when an answer leaned on a verified correction: "this follows a correction
  <person> made on <date>".
- Anyone can withdraw their own feedback, which archives the document it produced.

---

## 9. Tracking

Append one line per event to `kb/activity/<YYYY-MM>.jsonl`: question asked (with scope, latency,
passage count, model, semantic on/off), document added, document edited, feedback given. An
**Activity** panel on the Observability page shows: questions per week, the documents retrieved most
often, documents never retrieved once (the dead weight), the feedback rate, and the share of answers
where embeddings were unavailable.

---

## 10. Wiring, secrets and one-time grants

Include these in the build and print them at the end for a human to run:

```powershell
# Vertex embeddings for the platform runtime SA (it has only roles/run.developer today)
gcloud projects add-iam-policy-binding bidbrain-analytics `
  --member="serviceAccount:platform-dash-web@bidbrain-analytics.iam.gserviceaccount.com" `
  --role="roles/aiplatform.user"

# Kimi key for the platform service
gcloud secrets add-iam-policy-binding kimi-api-key `
  --member="serviceAccount:platform-dash-web@bidbrain-analytics.iam.gserviceaccount.com" `
  --role="roles/secretmanager.secretAccessor"
gcloud run services update platform-dash --region australia-southeast1 `
  --update-secrets=KIMI_API_KEY=kimi-api-key:latest
```

`deploy_dash_platform.ps1` is an image swap that preserves env and secrets, so the `run services
update` above is a one-time step. Add the new folders to the Dockerfile with `COPY`, the way
`explainers/` was added.

---

## 11. The self-knowledge document

Create `bidbrain-platform/dash/kb/HOW-BIDBRAIN-KB-WORKS.md`, modelled on Sentinel's
`docs/HOW-SENTINEL-WORKS.md`: what the knowledge base is, what is in it, how retrieval works, what
the picker does, what feedback does, and what the assistant must never claim. **Ship it inside the
prompt on every turn.** Any change to a rule in the build updates this file in the same commit.

---

## 12. Repo rules you must not break

From `md/AGENTS.md` and this repo's history:

- **No em dashes in any copy.** Use commas, colons or hyphens.
- **No client names** in anything that could be shared outward.
- Region is `australia-southeast1` everywhere. Never another.
- Never run `gcloud config set account/project`; pass `--project` and `--account` explicitly.
- Never commit a secret. Keys come from Secret Manager only.
- Windows PowerShell 5.1: no `&&`, no ternaries, quote `--set-secrets=` values,
  `gcloud run deploy` needs `--no-allow-unauthenticated --quiet`.
- Validate any dashboard JS with `scripts/_validate_dash_js.py` before deploying.
- **Docs are part of done**: update `bidbrain-platform/README.md` in the same change.
- Never create narrative summary `.md` files about your own work. The git log is the changelog.

---

## 13. Definition of done

- [ ] Every phase check in §7 passes.
- [ ] Flask test-client tests cover each gate in §3: staff yes, 100% Digital yes, Transmission 403,
      client 403, logged out redirected. Put them in `bidbrain-platform/dash/tests/test_kb.py`.
- [ ] Upload → searchable in under 30 seconds for a 30-page PDF, with progress visible.
- [ ] Vertex switched off by env: answers still work, the UI says keyword only, nothing 500s.
- [ ] Kimi key wrong: the answer falls back to Gemini and the panel says which model replied.
- [ ] A correction outranks the passage it corrects, demonstrated in the probe box.
- [ ] `bidbrain-platform/README.md` has a section for this, and `dash/kb/HOW-BIDBRAIN-KB-WORKS.md`
      matches the code.
- [ ] The three explainer pages at `/brain/how-it-works/*` still describe what the system now does;
      if a retrieval parameter differs from what they claim, fix the page in the same change.
- [ ] Deployed with `bidbrain-platform/dash/deploy_dash_platform.ps1` and checked live.

---

## 14. Do not

- Do not put this behind a client login, or show it to any agency other than 100% Digital.
- Do not index lead-level personal data, or anything from `raw_*` tables.
- Do not let the assistant change a campaign on any ad platform. It suggests; a person acts.
- Do not add a framework or a vector database to solve a problem the in-memory index has not yet had.
- Do not silently swallow a retrieval failure. A declared gap is a feature; a quiet one is a lie.
- Do not edit anything inside the Sentinel repo.

---

## 15. Start here

1. Read §2's files and say, in ten lines, what you understood the retrieval design to be.
2. List anything in this brief you think is wrong or under-specified, before building.
3. Then build phase 1.
