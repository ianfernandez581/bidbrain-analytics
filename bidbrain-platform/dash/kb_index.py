"""kb_index.py - HYBRID retrieval over the knowledge base, and the write path that feeds it.

TWO RETRIEVERS, FUSED. BM25 is the right tool for exact terms: a campaign name, "Q3", a brief
number, a person. It is also blind to paraphrase, so a note titled "Rate card rationale" scores
ZERO against "how do we decide what to charge a new account?" because not one content word
overlaps. Embeddings (kb_embed.py) catch exactly that and are correspondingly weak where BM25 is
strong, since a rare proper noun gets averaged away into a vector that is merely "about pricing".
So we run both and FUSE them.

🔴 FUSION IS BY RANK, NOT BY SCORE. A BM25 score is an unbounded corpus-relative number; a cosine
similarity is bounded and clusters tightly around 0.5 to 0.8 for anything on topic. Adding or
weighting them directly means one silently dominates, and WHICH one drifts as the corpus grows.
Reciprocal Rank Fusion throws the magnitudes away and keeps only the ordering, so it needs no
calibration and no held-out set, which matters because there is nobody here to maintain one.

🔴 THERE IS NO PER-VIEWER VISIBILITY PREDICATE HERE, AND THAT IS A REAL DIFFERENCE. The reference
implementation this is ported from has private-by-default documents and enforces visibility inside
the retriever. This library is not private-by-default: everybody who gets past the route gate
(staff, or a 100% Digital session) reads all of it. So the only hard filter is SCOPE, the knowledge
base picker's folders. Do not assume a document can be hidden from a colleague by putting it here.

🔴 THE CORPUS IS ARRAYS, NOT A LIST OF DICTS. A dict plus a 768-float Python list plus a Counter
per chunk measures around 40 KB a passage. One float32 matrix (3 KB a passage), an inverted index
for BM25 and the passage text is the difference between fitting in this service and not. Note the
service currently runs 512Mi with two gunicorn workers, and the index is PER PROCESS: two workers
hold two copies.

🔴 THE INDEX REFRESHES INCREMENTALLY, WHICH THE REFERENCE DOES NOT NEED TO. It rebuilds from one
streamed SQL query; we rebuild from GCS, where the same job is one GET per document. At a few
hundred documents that is fifteen seconds, serially, after EVERY write, on EVERY instance. So the
cache keeps each document's passages keyed by its object GENERATION and re-fetches only what
changed (kb_store.chunk_signature gives the check and the diff in one call). Re-tokenising is
still done in full on a rebuild: it is pure CPU, it is fast, and caching token counters per chunk
would put back the per-chunk dicts the paragraph above exists to avoid.

WHAT COMES BACK IS ALWAYS DECLARED. `semantic: False` plus the reason when embeddings were
unavailable, and an `outcome` string on EVERY return including the early ones. "There is genuinely
nothing about that", "the scope you picked is empty" and "nothing has been indexed yet" produce an
identical empty list, and only something that distinguishes them can answer "why did it say that?"
"""
import logging
import math
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import kb_chunk
import kb_embed
import kb_store
import kb_trace
from kb_chunk import tokenize

log = logging.getLogger(__name__)

# --- tuning -------------------------------------------------------------------------------------
K1 = 1.5                     # BM25 term-frequency saturation
B = 0.75                     # BM25 length normalisation
RRF_K = 60                   # the standard RRF constant; damps the top ranks' dominance
DEFAULT_LIMIT = 8
# How many candidates each retriever contributes to the fusion. Wider than the final limit on
# purpose: fusion can only promote what at least one retriever surfaced, so a passage BM25 ranks
# 15th and embeddings rank 3rd is exactly the kind of hit hybrid search exists to find.
CANDIDATES = 40
# At most this many passages from any one document, so a single long media plan cannot crowd out
# every other answer in the library.
MAX_PER_DOC = 2

# STRICT MODE'S TWO FLOORS. Fusion ranks; it never says "nothing here is relevant". That is fine
# when documents are searched only when a question is plainly about the written record, and wrong
# once the assistant searches every turn, where an unrelated question would still get eight
# passages that merely came first. 0.5 is where text-embedding-005 separates "about the same
# thing" from "shares a register".
SEMANTIC_FLOOR = 0.5
STRICT_MIN_TERMS = 2

# --- how hard trust moves a fused rank, and why these numbers -----------------------------------
# One retriever's 40 candidates span 1/61 = 0.01639 down to 1/100 = 0.01000, so the whole list is
# 0.0064 wide and adjacent ranks near the top are ~0.00027 apart. A passage found by BOTH
# retrievers near the top scores ~0.0328, roughly double a single-retriever first place.
#
# TRUST_NUDGE lifts a verified document about 12 to 15 ranks within one retriever's list: enough
# that a relevant correction reliably surfaces, NOT enough to beat a passage both retrievers ranked
# highly. A blanket "verified always wins" would mean any correction mentioning a topic outranks a
# genuinely better answer, which is the thing rank fusion exists to avoid.
TRUST_NUDGE = 0.004
# SUPERSEDED_PENALTY is what actually guarantees a correction outranks the passage it corrects, and
# it is TARGETED: it applies only to the specific passages a retrieved verified document names as
# corrected. Larger than the whole candidate span, so a superseded passage lands below everything
# else rather than merely lower.
SUPERSEDED_PENALTY = 0.02

# Marks a document whose passages are written but whose vectors are not built yet.
PENDING_EMBED = "pending: meaning search is still being built for this document"

# Parallelism for the incremental fetch. GCS reads are network-bound, so this is about latency,
# not CPU.
FETCH_WORKERS = 16


def _top(scores, k, valid):
    """The best `k` of `scores` where `valid`, highest first, ties broken by chunk order. An
    `argpartition` alone would cut a tie at the boundary arbitrarily, which makes a ranking move
    between runs for no reason anybody can see."""
    idx = np.flatnonzero(valid)
    if idx.size == 0:
        return []
    s = scores[idx]
    if idx.size > k:
        kth = np.partition(s, idx.size - k)[idx.size - k]        # the k-th largest value
        above = np.flatnonzero(s > kth)
        ties = np.flatnonzero(s == kth)[: k - above.size]
        sel = np.concatenate([above, ties])
        idx, s = idx[sel], s[sel]
    order = np.lexsort((idx, -s))
    return [(int(idx[i]), float(s[i])) for i in order]


class _Corpus:
    """Every live passage in the library with its BM25 statistics and its vector.

    🔴 ONE GLOBAL INDEX, MASKED PER SEARCH, not one index per scope. IDF is computed across the
    whole corpus on purpose: IDF over a per-scope subset makes the same passage rank differently
    depending on which folders somebody ticked, and corpus-wide term statistics are the more
    stable signal. Scope is applied when SCORING, so only in-scope passages can score at all.
    """

    __slots__ = ("signature", "built_at", "n", "texts", "vecs", "has_vec", "postings", "norm",
                 "idf", "avg_len", "meta", "slices", "chunk_ords", "pending_docs", "doc_of")

    def __init__(self, docs, signature):
        """`docs` is an ordered list of (doc_id, meta, texts, vecs ndarray|None, has_vec)."""
        self.signature = signature
        self.built_at = time.monotonic()
        self.meta = {}
        self.slices = {}                     # doc_id -> (start, end) into the flat chunk arrays
        self.pending_docs = set()
        texts = []
        chunk_ords = []
        doc_of = []
        lengths = []
        df = Counter()
        post_idx = {}
        post_tf = {}
        vec_blocks = []
        has_vec_parts = []
        dim = 0

        i = 0
        for doc_id, meta, dtexts, dvecs, dhas in docs:
            start = i
            title = meta.get("title") or ""
            for ord_, text in enumerate(dtexts):
                texts.append(text)
                chunk_ords.append(ord_)
                doc_of.append(doc_id)
                # Title folded into every chunk's tokens: the name a question searches by is often
                # not repeated inside the passage itself.
                toks = tokenize(text + " " + title)
                lengths.append(float(len(toks)))
                for term, f in Counter(toks).items():
                    df[term] += 1
                    if term not in post_idx:
                        post_idx[term] = []
                        post_tf[term] = []
                    post_idx[term].append(i)
                    post_tf[term].append(float(f))
                i += 1
            self.slices[doc_id] = (start, i)
            self.meta[doc_id] = meta
            if dvecs is not None and dvecs.size:
                dim = dim or int(dvecs.shape[1])
            vec_blocks.append((start, dvecs))
            has_vec_parts.append(dhas)

        self.n = len(texts)
        self.texts = texts
        self.chunk_ords = np.array(chunk_ords, dtype=np.int32) if self.n else np.zeros(0, np.int32)
        self.doc_of = doc_of
        self.has_vec = (np.concatenate(has_vec_parts) if has_vec_parts and self.n
                        else np.zeros(self.n, dtype=bool))
        if dim and self.n:
            self.vecs = np.zeros((self.n, dim), dtype=np.float32)
            for start, block in vec_blocks:
                if block is None or not block.size:
                    continue
                rows = block.shape[0]
                if block.shape[1] == dim:
                    self.vecs[start:start + rows] = block
                else:
                    # Vectors from a DIFFERENT model are not comparable to these. Mark those
                    # chunks unembedded rather than leaving them as zero rows, which would score a
                    # meaningless cosine of 0 and still count as a semantic candidate.
                    self.has_vec[start:start + rows] = False
        else:
            self.vecs = None
        # Computed from the FINAL has_vec, after the dim check above, so a document whose vectors
        # were rejected is reported as pending rather than as embedded.
        for doc_id, (s, e) in self.slices.items():
            if e > s and not bool(np.any(self.has_vec[s:e])):
                self.pending_docs.add(doc_id)
        lens = np.array(lengths, dtype=np.float64) if self.n else np.zeros(0)
        self.avg_len = float(lens.mean()) if self.n else 1.0
        self.norm = K1 * (1 - B + B * np.maximum(lens, 1.0) / (self.avg_len or 1.0))
        n = max(1, self.n)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.postings = {t: (np.array(post_idx[t], dtype=np.int64),
                             np.array(post_tf[t], dtype=np.float64))
                         for t in post_idx}

    # --- scope ----------------------------------------------------------------------------------

    def doc_ids_in_scope(self, folders):
        """The documents a search may read. `folders` empty or None means the whole library.
        Ticking a folder includes everything below it, which is what a tree picker means."""
        wanted = normalize_folders(folders)
        if not wanted:
            return set(self.meta)
        out = set()
        for doc_id, meta in self.meta.items():
            f = meta.get("folder") or ""
            for w in wanted:
                if w == ROOT_FOLDER:                  # documents that sit in no folder at all
                    if not f:
                        out.add(doc_id)
                elif f == w or f.startswith(w + "/"):
                    out.add(doc_id)
        return out

    def mask(self, doc_ids):
        """A boolean over every chunk. Built from each document's contiguous slice rather than an
        `isin` over ids, because the corpus is assembled document by document."""
        m = np.zeros(self.n, dtype=bool)
        for doc_id in doc_ids:
            sl = self.slices.get(doc_id)
            if sl:
                m[sl[0]:sl[1]] = True
        return m

    # --- the two retrievers ---------------------------------------------------------------------

    def bm25(self, query, allowed, min_terms=1):
        q = tokenize(query)
        if not q or not self.n:
            return []
        scores = np.zeros(self.n, dtype=np.float64)
        hits = np.zeros(self.n, dtype=np.int32) if min_terms > 1 else None
        seen = set()
        for term in q:                       # duplicates count twice, as BM25 intends
            p = self.postings.get(term)
            if p is None:
                continue
            idx, tf = p
            scores[idx] += self.idf.get(term, 0.0) * (tf * (K1 + 1)) / (tf + self.norm[idx])
            if hits is not None and term not in seen:
                hits[idx] += 1
                seen.add(term)
        valid = allowed & (scores > 0)
        if hits is not None:
            # Measured against the QUESTION's distinct words, not just the ones the library happens
            # to contain: the other way round, a question sharing one ordinary word with the whole
            # library passes the floor it exists to stop.
            valid &= hits >= min(min_terms, len(set(q)))
        return _top(scores, CANDIDATES, valid)

    def semantic(self, qvec, allowed, floor=None):
        if self.vecs is None or not self.n:
            return []
        q = np.asarray(qvec, dtype=np.float32)
        if q.shape[0] != self.vecs.shape[1]:
            return []
        sims = (self.vecs @ q).astype(np.float64)
        valid = allowed & self.has_vec
        if floor is not None:
            valid &= sims >= floor
        return _top(sims, CANDIDATES, valid)


ROOT_FOLDER = "/"          # the scope entry meaning "documents that sit in no folder at all"


def normalize_folders(folders):
    """The picker's selection, cleaned. `/` is kept verbatim; everything else goes through the
    store's one folder convention."""
    out = []
    for f in (folders or []):
        s = str(f or "").strip()
        if s == ROOT_FOLDER:
            out.append(ROOT_FOLDER)
            continue
        n = kb_store.normalize_folder(s)
        if n:
            out.append(n)
    return sorted(set(out))


class _IndexCache:
    """Holds the corpus until the library changes.

    Invalidated two ways, belt and braces: explicitly after a write in THIS process, and by the
    object-generation signature, which is what makes the OTHER Cloud Run instances notice. Only
    the instance that served an upload can invalidate its own memory.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._build_lock = threading.Lock()
        self._corpus = None
        self._docs = {}          # doc_id -> {gen, meta, texts, vecs, has_vec}: the fetch cache
        self._last_error = ""
        # What the last rebuild actually cost. `fetched` is the claim the incremental design makes
        # and the number a test can assert on: change one document of three and it must read one.
        self._stats = {"rebuilds": 0, "fetched": 0, "build_ms": 0, "sig_ms": 0}

    def invalidate(self):
        with self._lock:
            self._corpus = None

    def status(self):
        with self._lock:
            c = self._corpus
        return {"chunks": c.n if c else 0, "documents": len(c.meta) if c else 0,
                "pending_embedding": len(c.pending_docs) if c else 0,
                "cached_documents": len(self._docs), "last_error": self._last_error,
                "built_ago_s": round(time.monotonic() - c.built_at, 1) if c else None,
                **self._stats}

    def get(self):
        t0 = time.monotonic()
        sig = tuple(kb_store.chunk_signature())
        self._stats["sig_ms"] = int((time.monotonic() - t0) * 1000)
        with self._lock:
            if self._corpus is not None and self._corpus.signature == sig:
                return self._corpus
        # One rebuild at a time: two concurrent searches after a write must not both pay for it,
        # and must not briefly hold two copies of the library in memory.
        with self._build_lock:
            with self._lock:
                if self._corpus is not None and self._corpus.signature == sig:
                    return self._corpus
            corpus = self._build(sig)
            with self._lock:
                self._corpus = corpus
            return corpus

    def _build(self, sig):
        t0 = time.monotonic()
        live = {doc_id: (name, gen) for doc_id, name, gen in sig}
        # Drop what is gone, fetch what is new or changed. This is the whole reason the signature
        # carries generations.
        for doc_id in [d for d in self._docs if d not in live]:
            self._docs.pop(doc_id, None)
        todo = [(doc_id, name) for doc_id, (name, gen) in live.items()
                if self._docs.get(doc_id, {}).get("gen") != gen]
        if todo:
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(todo))) as pool:
                for doc_id, loaded in zip([t[0] for t in todo],
                                          pool.map(lambda t: kb_store.read_chunks_by_name(t[1]), todo)):
                    rec = _load_doc_record(loaded, live[doc_id][1])
                    if rec is None:
                        self._docs.pop(doc_id, None)
                    else:
                        self._docs[doc_id] = rec
            log.info("kb: fetched %d changed document(s) in %.2fs", len(todo),
                     time.monotonic() - started)
        self._stats["rebuilds"] += 1
        self._stats["fetched"] = len(todo)

        docs = []
        for doc_id in sorted(self._docs):
            rec = self._docs[doc_id]
            # Archived documents stay in storage and leave the index. An empty document has no
            # passages and would only widen the scope set with nothing to score.
            if rec["meta"].get("archived") or not rec["texts"]:
                continue
            docs.append((doc_id, rec["meta"], rec["texts"], rec["vecs"], rec["has_vec"]))
        corpus = _Corpus(docs, sig)
        self._stats["build_ms"] = int((time.monotonic() - t0) * 1000)
        return corpus


def _load_doc_record(obj, gen):
    """One chunks object into the shape the cache holds. Base64 is decoded ONCE here rather than on
    every rebuild, and a corrupt or wrongly-sized vector degrades that chunk to keyword-only
    instead of breaking the document."""
    if not isinstance(obj, dict):
        return None
    meta = obj.get("doc") or {}
    chunks = obj.get("chunks") or []
    texts = []
    rows = []
    dim = 0
    for c in chunks:
        if not isinstance(c, dict):
            continue
        texts.append(str(c.get("text") or ""))
        v = kb_embed.unpack(c.get("embedding") or "")
        if v and not dim:
            dim = len(v)
        rows.append(v if (v and len(v) == dim) else None)
    if not texts:
        return {"gen": gen, "meta": meta, "texts": [], "vecs": None,
                "has_vec": np.zeros(0, dtype=bool)}
    has_vec = np.array([r is not None for r in rows], dtype=bool)
    if dim:
        mat = np.zeros((len(rows), dim), dtype=np.float32)
        for i, r in enumerate(rows):
            if r is not None:
                mat[i] = np.asarray(r, dtype=np.float32)
    else:
        mat = None
    return {"gen": gen, "meta": meta, "texts": texts, "vecs": mat, "has_vec": has_vec}


_INDEX = _IndexCache()


def invalidate():
    _INDEX.invalidate()


def status():
    return _INDEX.status()


def all_meta(include_archived=True):
    """Every document's metadata, from the index's own fetch cache.

    🔴 THIS IS WHY THE FILE LIST IS CHEAP. The cache already holds one `doc` header per document
    (kb_store.doc_meta), so drawing a library of five hundred rows costs no reads at all. Listing
    from `docs/` instead would be five hundred GETs of five hundred full bodies, per page view.
    Archived documents are IN this list and out of the corpus: they still have a row in the
    Explorer's Archived view, and they are unsearchable.
    """
    _INDEX.get()                                  # refresh the fetch cache against the listing
    out = {}
    for doc_id, rec in _INDEX._docs.items():      # noqa: SLF001 - same module's own cache
        meta = dict(rec["meta"] or {})
        if meta.get("archived") and not include_archived:
            continue
        meta["id"] = meta.get("id") or doc_id
        meta["chunks"] = len(rec["texts"])
        meta["embedded"] = int(np.count_nonzero(rec["has_vec"])) if len(rec["texts"]) else 0
        out[doc_id] = meta
    return out


def folder_counts(include_archived=False):
    """Document counts per folder path, with every ANCESTOR carrying the total beneath it. That is
    what a tree with counts means: ticking `Media plans` includes everything below it, so its count
    has to say so."""
    counts = {}
    for meta in all_meta(include_archived=include_archived).values():
        f = meta.get("folder") or ""
        if not f:
            counts[ROOT_FOLDER] = counts.get(ROOT_FOLDER, 0) + 1
            continue
        parts = f.split("/")
        for i in range(len(parts)):
            path = "/".join(parts[:i + 1])
            counts[path] = counts.get(path, 0) + 1
    return counts


# --- the write path ------------------------------------------------------------------------------

def reindex_document(doc, *, force=False, embed=True, two_phase=True):
    """(Re)build one document's passages and vectors, and write it. Idempotent and cheap when
    nothing changed. Returns a small report for the UI and for tests.

    🔴 KEYWORD SEARCH SURVIVES AN EMBEDDING FAILURE. With `two_phase`, the passages are written
    FIRST, without vectors, so the document is findable by wording the moment the upload returns;
    the vectors are a second, best-effort pass. A Vertex outage therefore degrades ranking quality
    and is REPORTED (`embed_error`), instead of dropping the document out of the library entirely.
    """
    want = kb_chunk.content_hash(doc.get("title") or "", doc.get("body") or "")
    if not force and doc.get("indexed_hash") == want:
        existing = kb_store.read_chunks(doc["id"])
        # A model change invalidates every vector, since vectors are not comparable across models,
        # so a matching hash is only reusable if the vectors came from the model we would use now.
        if existing and (existing.get("model") == kb_embed.model_name()
                         or not (doc.get("body") or "").strip()):
            return {"chunks": len(existing.get("chunks") or []), "skipped": True,
                    "semantic": not doc.get("embed_error"), "error": doc.get("embed_error") or ""}

    body = doc.get("body") or ""
    truncated = 0
    if len(body) > kb_store.MAX_BODY_CHARS:
        truncated = len(body) - kb_store.MAX_BODY_CHARS
        body = body[:kb_store.MAX_BODY_CHARS]
    texts = kb_chunk.chunk_text(body)

    if two_phase and texts and embed:
        # Searchable by wording the moment the upload returns. The row shows "indexing" because
        # this object has passages and no vectors, which is a state the list can read without
        # anybody having to invent a status field.
        doc["embed_error"] = ""
        kb_store.write_chunks(doc, [{"ord": i, "text": t, "embedding": ""}
                                    for i, t in enumerate(texts)], model="")

    error = ""
    vectors = None
    if texts and embed:
        if kb_embed.enabled():
            vectors, error = kb_embed.embed_documents(texts, title=doc.get("title") or "")
        else:
            error = "Vertex embeddings are switched off for this deployment"
    elif texts:
        error = PENDING_EMBED

    chunks = []
    for i, t in enumerate(texts):
        blob = kb_embed.pack(vectors[i]) if vectors else ""
        chunks.append({"ord": i, "text": t, "embedding": blob})

    # 🔴 THE BOOKKEEPING IS SET BEFORE THE CHUNKS ARE WRITTEN, not after. The chunks object carries
    # a COPY of the document's metadata and that copy is what the file list reads, so writing it
    # first would publish the PREVIOUS run's `embed_error` and leave a document that failed to
    # embed looking, in the list, exactly like one that succeeded.
    doc["indexed_at"] = kb_store.now()
    doc["indexed_hash"] = want
    doc["embed_error"] = (error or "")[:200]
    kb_store.write_chunks(doc, chunks, model=kb_embed.model_name() if vectors else "")
    kb_store.write_doc(doc)
    invalidate()
    if error:
        log.warning("kb: document %s indexed without vectors: %s", doc.get("id"), error)
    return {"chunks": len(chunks), "skipped": False, "semantic": bool(vectors),
            "error": error, "truncated_chars": truncated}


def refresh_manifest():
    """Recount the library for the Observability page. Never on the hot path: freshness comes from
    the object listing (see kb_store)."""
    c = _INDEX.get()
    embedded = int(np.count_nonzero(c.has_vec)) if c.n else 0
    return kb_store.write_manifest(len(c.meta), c.n, embedded)


# --- search --------------------------------------------------------------------------------------

def search(q, *, limit=DEFAULT_LIMIT, folders=None, strict=False, trust_bonus=True):
    """The passages in the library that bear on `q`, within the scope the picker set.

    `folders` is the SCOPE and the ONLY hard filter: it narrows the candidate set BEFORE scoring,
    never after, because filtering afterwards means a scoped search silently returns fewer than
    `limit` passages while relevant in-scope ones went unranked.
    """
    started = time.monotonic()
    out = {"excerpts": [], "semantic": False, "semantic_error": "", "documents_searched": 0,
           "unembedded_documents": 0, "query": (q or "").strip(), "outcome": "", "ms": 0,
           "index_ms": 0, "embed_ms": 0, "scope": normalize_folders(folders)}

    # 🔴 THE SPAN WRAPS THE WHOLE FUNCTION, EVERY EARLY RETURN INCLUDED. A search that answered
    # nothing is the most interesting thing an observability page exists to explain: "there is
    # genuinely nothing about that", "the scope you picked is empty" and "the index is empty" are
    # three very different failures that produce the identical empty list, and only something that
    # exists for all three tells them apart. Every return goes through `done()`, which is why
    # `outcome` is never blank.
    with kb_trace.span("kb.search", kb_trace.RETRIEVER) as sp:
        return _search(q, limit, folders, strict, trust_bonus, out, started, sp)


def _search(q, limit, folders, strict, trust_bonus, out, started, sp):
    def done(outcome):
        out["outcome"] = outcome
        out["ms"] = int((time.monotonic() - started) * 1000)
        sp.set(outcome=outcome, ms=out["ms"], semantic=out["semantic"],
               semantic_error=out["semantic_error"] or None,
               documents_visible=out["documents_searched"],
               unembedded_documents=out["unembedded_documents"],
               passages=len(out["excerpts"]))
        sp.output("%s" % outcome)
        return out

    sp.input(out["query"])
    sp.set(limit=limit, strict=strict,
           folders=" | ".join(out["scope"]) or None)
    query = (q or "").strip()
    if not query:
        return done("empty query")
    t_idx = time.monotonic()
    corpus = _INDEX.get()
    out["index_ms"] = int((time.monotonic() - t_idx) * 1000)
    if not corpus.n:
        return done("the index is empty; nothing has been indexed yet")
    allowed_docs = corpus.doc_ids_in_scope(folders)
    out["documents_searched"] = len(allowed_docs)
    if not allowed_docs:
        return done("the scope you picked contains no documents")
    mask = corpus.mask(allowed_docs)
    out["unembedded_documents"] = len(corpus.pending_docs & allowed_docs)

    keyword = corpus.bm25(query, mask, min_terms=STRICT_MIN_TERMS if strict else 1)

    semantic = []
    if kb_embed.enabled():
        t_emb = time.monotonic()
        qvec, err = kb_embed.embed_query(query)
        out["embed_ms"] = int((time.monotonic() - t_emb) * 1000)
        if qvec:
            semantic = corpus.semantic(qvec, mask, floor=SEMANTIC_FLOOR if strict else None)
            out["semantic"] = True
        else:
            out["semantic_error"] = err
    else:
        out["semantic_error"] = "Vertex embeddings are switched off for this deployment"

    # --- Reciprocal Rank Fusion. See the module header for why rank and not score.
    fused = {}
    found_by = {}
    rank_in = {}
    cosine = dict(semantic)
    for name, ranked in (("keyword", keyword), ("semantic", semantic)):
        for rank, (idx, _score) in enumerate(ranked):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
            found_by.setdefault(idx, set()).add(name)
            # Kept because the per-retriever rank is what makes fusion legible: "neither list had
            # this in its top eight and fusion put it first" is the behaviour hybrid search is
            # bought for, and a fused score on its own cannot show it.
            rank_in.setdefault(idx, {})[name] = rank + 1

    # The pair of numbers that answers "was this actually hybrid, or did it quietly degrade to
    # keyword only?" The payload answers it with one boolean; a trace answers it with the evidence.
    sp.set(keyword_candidates=len(keyword), semantic_candidates=len(semantic))

    if not fused:
        return done("neither retriever matched anything in scope")

    # Trust, and the passages a retrieved correction supersedes. Both are applied AFTER fusion, on
    # the fused score, so neither can add a passage that no retriever found.
    superseded = set()
    if trust_bonus:
        for idx in fused:
            meta = corpus.meta.get(corpus.doc_of[idx]) or {}
            if (meta.get("trust") or "") == kb_store.TRUST_VERIFIED:
                fused[idx] += TRUST_NUDGE
                for ref in meta.get("supersedes") or []:
                    superseded.add(str(ref))
    if superseded:
        for idx in fused:
            doc_id = corpus.doc_of[idx]
            if doc_id in superseded or f"{doc_id}#{int(corpus.chunk_ords[idx])}" in superseded:
                fused[idx] -= SUPERSEDED_PENALTY

    order = sorted(fused.items(), key=lambda kv: -kv[1])
    excerpts = []
    per_doc = Counter()
    for idx, score in order:
        doc_id = corpus.doc_of[idx]
        meta = corpus.meta.get(doc_id)
        if not meta:
            continue
        if per_doc[doc_id] >= MAX_PER_DOC:
            continue
        per_doc[doc_id] += 1
        ranks = rank_in.get(idx, {})
        excerpts.append({
            "document_id": doc_id, "title": meta.get("title") or "",
            "folder": meta.get("folder") or "", "kind": meta.get("kind") or "",
            "trust": meta.get("trust") or kb_store.TRUST_STANDARD,
            "owner": meta.get("owner") or "", "updated_at": meta.get("updated_at") or 0,
            "ord": int(corpus.chunk_ords[idx]),
            "passage_id": f"{doc_id}#{int(corpus.chunk_ords[idx])}",
            "passage": corpus.texts[idx],
            "score": round(score, 5),
            "found_by": sorted(found_by.get(idx, ())),
            "keyword_rank": ranks.get("keyword"),
            "semantic_rank": ranks.get("semantic"),
            "semantic_score": round(cosine[idx], 4) if idx in cosine else None,
        })
        if len(excerpts) >= max(1, limit):
            break
    out["excerpts"] = excerpts
    sp.documents(excerpts, meta_keys=("title", "folder", "trust", "found_by", "keyword_rank",
                                      "semantic_rank", "semantic_score", "owner"))
    return done("%d passage(s) from %d document(s)"
                % (len(excerpts), len({e["document_id"] for e in excerpts})))
