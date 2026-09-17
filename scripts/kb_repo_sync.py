#!/usr/bin/env python
"""kb_repo_sync.py - this repo's markdown, mirrored into the knowledge base at /kb.

WHY IT EXISTS. The estate's real documentation is markdown in this repo: AGENTS.md, every client
README, every ingest unit, the platform and Grid guides. The knowledge base answers questions over
the agency's WRITTEN record and this is the largest part of it. Uploading it by hand once would be
an IMPORT, not a source of truth: the day somebody edits a README the library starts answering from
the old wording, quietly, and nothing on screen says so. So this is a SYNC - idempotent, safe to
re-run, and cheap enough to run on every push.

It writes through the SAME code path the Explorer's own upload uses (`kb_index.reindex_document`),
so there is no second definition of what a document is, how it is chunked, or how it is embedded.

🔴 SECTIONS, NOT FILES. A 230,000-character README loaded as ONE document gives every passage in it
the same title - and the title is what `kb_embed` attaches to EVERY chunk's vector and what
`kb_index` folds into its BM25 tokens (`tokenize(text + " " + title)`). One document per heading is
what puts "client_cloudflare/README.md > The motion layer" into both retrievers instead of the word
"README". This is the single biggest lever on answer quality here, and it costs nothing.

🔴 THE CLIENTS TABLE IN AGENTS.md IS SPLIT PER ROW. That table is one row per client and the client's
name appears ONCE, at the start of a line that runs to several thousand words. Chunked as prose, the
first passage knows it is about mongodb and the next eleven do not - they read as unattributed rules
about somebody's dashboard. One document per row, titled with the client key, fixes it.

🔴 SPLIT, NEVER REWRITE. Nothing here paraphrases, summarises or reflows a source. A knowledge base
that improves its own sources answers from text that exists nowhere, and a reader following the
citation back into git finds something else. Headings are re-emitted verbatim and one breadcrumb
line is added. That is the whole of the transformation.

🔴 DETERMINISTIC IDS ARE WHAT MAKE THIS A SYNC AND NOT AN IMPORT. A document's id is a hash of its
FILE PATH and its HEADING PATH, so the same section lands on the same document every run: an edit
updates in place and keeps its revision trail instead of adding a second copy of itself beside the
first. The cost is that RENAMING a heading retires one document and creates another, which is the
honest outcome - it is a different section now.

🔴 IT OWNS ONLY WHAT IT CREATED. Every id it writes starts with `repo_`; it only ever deletes ids
with that prefix; it never touches a document a person wrote. A markdown file deleted from the repo
takes its documents with it, because git is the history and a tombstone in the library is only a
stale answer waiting to be retrieved.

🔴 LINE ENDINGS ARE NORMALISED BEFORE ANYTHING IS HASHED. Git checks this repo out with CRLF on
Windows and LF in CI. The document ids are unaffected, but the CONTENT HASH is not: without this,
every run from the other platform would rewrite and re-embed all 164 files - minutes of Vertex calls
to change precisely nothing.

🔴 A HUMAN EDIT TO A SYNCED DOCUMENT IS OVERWRITTEN, BUT NEVER LOST. The repo is the source of
truth, so the file's text wins. When the document was last touched by somebody other than this
script, the existing text is pushed onto the revision trail first, so it is one click to read back.
Edit the markdown in git, not the document in the library.

Run it:

    .\\.venv\\Scripts\\python.exe scripts\\kb_repo_sync.py --dry-run     # plan only, writes nothing
    .\\.venv\\Scripts\\python.exe scripts\\kb_repo_sync.py --yes         # apply

Credentials: anything `google.auth.default()` resolves, with write access to the platform bucket and
`roles/aiplatform.user` for embeddings. On a laptop that is `gcloud auth application-default login`;
in CI it is the workload identity in `.github/workflows/kb-sync.yml`.

Embeddings fail SOFT, exactly as they do for an upload: the passages are written first and the
document is findable by wording even if Vertex is unavailable, the run reports it, and the next run
picks the vectors up. `--no-embed` makes that the deliberate choice (a fast structural load).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

# --- what gets written, and where ----------------------------------------------------------------

DEFAULT_BUCKET = "bidbrain-analytics-platform-dash"

# The one folder the whole mirror lives under, inside the agency-wide (no client) scope.
#
# 🔴 THIS IS THE ONLY PLACE THE FOLDER CAN BE RENAMED. `folder` is a FIELD on each document and the
# sync writes the repo's answer for it, so renaming the folder in the Explorer moves the documents
# for exactly as long as it takes the next run to move them all back - which looks, from the UI,
# like a rename that half worked and left a duplicate behind. Change it here and re-run.
#
# It is NOT called "Bidbrain analytics" (the repo's own name) on purpose: the assistant answers for
# an agency called Bidbrain, out of a library that already holds a "Bidbrain-backend" folder for a
# different repo, so a third Bidbrain was a name collision in the one place names are used to tell
# things apart.
TOP_FOLDER = "GCP Backend"

# 🔴 EVERY DOCUMENT THIS SCRIPT OWNS STARTS WITH THIS, and nothing else in the library does
# (`kb_store.new_id` produces `d_<epoch>_<hex>`). It is the entire basis on which a document may be
# deleted, so do not widen it and do not let a person's document be given one by hand.
ID_PREFIX = "repo_"

KIND = "reference"          # kb_store.KINDS
SOURCE = "paste"            # kb_store.SOURCES. NOT "upload": that offers a "Download original"
                            # in the Explorer, and there is no original object behind these.
OWNER = "bidbrain-analytics repo sync"

# Section sizing. MAX is the point at which a section is split further; MIN is the point below which
# a section is packed together with the ones after it, so a two-line heading does not become a
# document of its own. Both are in characters, and both are a judgement, not a law.
MAX_DOC_CHARS = 14_000
MIN_DOC_CHARS = 1_200

# Headings at or above this level start a new document. 1 and 2 both do, because several READMEs in
# this repo use `#` as a section divider rather than as a single document title.
SPLIT_LEVEL = 2
SUB_SPLIT_LEVEL = 3         # what an oversized section is cut on before falling back to blocks

# Left out of the mirror. Keep this list SHORT and say why: a document that is not here cannot be
# cited, and "it seemed like noise" is how a library ends up missing the one page somebody needed.
EXCLUDE = (
    "**/node_modules/**",
    ".venv/**",
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
KB_DIR = os.path.join(REPO, "bidbrain-platform", "dash")

sys.path.insert(0, KB_DIR)
os.environ.setdefault("GCS_BUCKET", DEFAULT_BUCKET)

import kb_chunk        # noqa: E402  (path set above)
import kb_embed        # noqa: E402
import kb_index        # noqa: E402
import kb_store        # noqa: E402


# --- reading the repo ----------------------------------------------------------------------------

def git(*args):
    out = subprocess.run(("git",) + args, cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out.stdout


def tracked_markdown(only=None):
    """Every markdown file GIT knows about, which is the same set GitHub has.

    🔴 TRACKED, NOT FOUND ON DISK. `git ls-files` is what makes the laptop run and the CI run agree:
    a scratch note, a vendored dependency's README and anything gitignored are all invisible to it,
    so nothing can reach the library that is not in the repo everybody shares.
    """
    files = [p.strip() for p in git("ls-files", "*.md").splitlines() if p.strip()]
    keep = []
    for rel in files:
        if any(fnmatch.fnmatch(rel, pat) for pat in EXCLUDE):
            continue
        if only and not any(fnmatch.fnmatch(rel, o) for o in only):
            continue
        keep.append(rel)
    return sorted(keep)


def read_text(rel):
    """The file as text, with line endings normalised. See the header on why that matters."""
    with open(os.path.join(REPO, rel), "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --- markdown into sections ----------------------------------------------------------------------

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")


def outline(text):
    """[(level, heading, body_lines)] for one file, the preamble first as level 0.

    🔴 CODE FENCES ARE TRACKED. A `## ` inside a fenced block is a shell comment or a markdown
    example, not a heading, and treating it as one cuts a document in half mid-example.
    """
    nodes, fence = [], ""
    level, title, body = 0, "", []
    for line in text.split("\n"):
        m = FENCE.match(line)
        if m:
            tok = m.group(1)[0] * 3
            if not fence:
                fence = tok
            elif line.strip().startswith(fence):
                fence = ""
            body.append(line)
            continue
        if not fence:
            h = HEADING.match(line)
            if h:
                nodes.append((level, title, body))
                level, title, body = len(h.group(1)), h.group(2).strip(), []
                continue
        body.append(line)
    nodes.append((level, title, body))
    return [n for n in nodes if n[1] or "\n".join(n[2]).strip()]


def render(nodes):
    """Nodes back into markdown, verbatim apart from the spacing between a heading and its body."""
    parts = []
    for level, title, body in nodes:
        if level:
            parts.append("#" * level + " " + title)
        text = "\n".join(body).strip("\n")
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts).strip()


def _group(nodes, split_level):
    """Consecutive nodes cut at every heading of `split_level` or shallower."""
    out, cur = [], None
    for node in nodes:
        level = node[0]
        if cur is None or (level and level <= split_level):
            cur = [node]
            out.append(cur)
        else:
            cur.append(node)
    return out


def sections(text):
    """A file into top-level sections, small neighbours packed together."""
    groups = [{"nodes": list(g), "size": len(render(g))} for g in _group(outline(text), SPLIT_LEVEL)]
    packed = []
    for g in groups:
        if packed and packed[-1]["size"] < MIN_DOC_CHARS \
                and packed[-1]["size"] + g["size"] <= MAX_DOC_CHARS:
            packed[-1]["nodes"].extend(g["nodes"])
            packed[-1]["size"] += g["size"]
        else:
            packed.append({"nodes": list(g["nodes"]), "size": g["size"]})
    return packed


def first_cell(row):
    """The label a table row files itself under: its first cell, stripped of markdown."""
    cells = [c for c in CELL_SPLIT.split(row.strip())]
    if cells and not cells[0].strip():
        cells = cells[1:]
    raw = cells[0] if cells else ""
    return re.sub(r"[`*_]", "", raw).strip()


def split_table(body):
    """An oversized markdown table into ONE PART PER ROW, the header repeated on each.

    -> [(label, text)], or None when there is no table big enough to be worth it. Whatever sits
    before and after the table stays with it, as its own parts, so nothing is dropped.

    🔴 ONE ROW, ONE DOCUMENT - rows are never packed together. Packing small rows up to the budget
    is the obvious economy and it throws away the only thing this split exists to preserve: five
    clients in one document means a passage about proptrack carries a title naming four other
    clients, into both retrievers. A 500-character document is not a problem; a mislabelled one is.
    """
    lines = body.split("\n")
    start = None
    for i, line in enumerate(lines):
        if TABLE_ROW.match(line) and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1]):
            start = i
            break
    if start is None:
        return None
    end = start + 2
    while end < len(lines) and TABLE_ROW.match(lines[end]):
        end += 1
    header, sep, rows = lines[start], lines[start + 1], lines[start + 2:end]
    if len(rows) < 2 or len("\n".join(lines[start:end])) <= MAX_DOC_CHARS:
        return None
    before = "\n".join(lines[:start]).strip()
    after = "\n".join(lines[end:]).strip()

    parts = []
    if before:
        parts.append((None, before))
    for row in rows:
        parts.append((first_cell(row), "\n".join([header, sep, row])))
    if after:
        parts.append((None, after))
    return parts


# A sentence end, used only to choose WHERE to cut something already too big to leave whole.
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*`(\[])")


def split_run(body):
    """Text too big for one document, cut to the budget and nothing else.

    Blocks first (blank lines), then sentence ends, then - only if one sentence is somehow bigger
    than the whole budget - words. Every cut is at a boundary that already existed in the text.

    🔴 THIS RUNS ON MORE THAN PROSE. `kb_index.MAX_PER_DOC` is 2: a document contributes at most two
    passages to any answer, whatever its length. So a 40,000-character table row left whole is not
    merely a large document, it is 180 passages of which 2 can ever be cited - which is how a
    client's entire section of AGENTS.md ends up answering one question about itself and no more.
    """
    def pack(pieces, joiner):
        out, cur, size = [], [], 0
        for piece in pieces:
            if cur and size + len(piece) > MAX_DOC_CHARS:
                out.append(joiner.join(cur))
                cur, size = [], 0
            cur.append(piece)
            size += len(piece) + len(joiner)
        if cur:
            out.append(joiner.join(cur))
        return out

    parts = []
    for block in pack([b for b in re.split(r"\n\s*\n", body) if b.strip()] or [body], "\n\n"):
        if len(block) <= MAX_DOC_CHARS:
            parts.append(block)
            continue
        for run in pack(SENTENCE.split(block), " "):
            if len(run) <= MAX_DOC_CHARS:
                parts.append(run)
            else:
                parts.extend(pack(run.split(" "), " "))
    return parts or [body]


def _parts(path, text):
    """One piece of a section as the document(s) it becomes, numbered only when there is a second."""
    if len(text) <= MAX_DOC_CHARS:
        return [(path, text)]
    parts = split_run(text)
    if len(parts) == 1:
        return [(path, parts[0])]
    return [(path + ["part %d of %d" % (i, len(parts))], p) for i, p in enumerate(parts, 1)]


def section_documents(nodes):
    """One section into the documents it should become: [(heading_path, body)].

    The ladder is heading, then sub-heading, then table row, then text - each step used only when
    the one before it left something over the budget.
    """
    body = render(nodes)
    head = nodes[0][1] if nodes and nodes[0][0] else ""
    path = [head] if head else []
    if len(body) <= MAX_DOC_CHARS:
        return [(path, body)]

    out = []
    for sub in _group(nodes, SUB_SPLIT_LEVEL):
        sub_body = render(sub)
        sub_head = sub[0][1] if sub[0][0] and sub[0][0] > SPLIT_LEVEL else ""
        sub_path = path + ([sub_head] if sub_head else [])
        if len(sub_body) <= MAX_DOC_CHARS:
            out.append((sub_path, sub_body))
            continue

        table = split_table(sub_body)
        if table:
            for label, text in table:
                out.extend(_parts(sub_path + ([label] if label else []), text))
            continue
        out.extend(_parts(sub_path, sub_body))
    return out


# --- sections into documents ---------------------------------------------------------------------

def folder_for(rel):
    directory = os.path.dirname(rel)
    return TOP_FOLDER if not directory else "%s/%s" % (TOP_FOLDER, directory)


def title_for(rel, path):
    return kb_store.one_line(" > ".join([rel] + [p for p in path if p]))


def breadcrumb(rel, path):
    """The provenance block at the top of every document, so the first passage - and anybody
    reading the document in the Explorer - can say where the text came from without leaving the
    page, and knows not to edit it here.

    🔴 NO COMMIT SHA IN HERE. It would change the body on every commit, which changes the content
    hash, which re-embeds the entire library on every run to say nothing new.
    """
    line = "> Source: `%s` in the bidbrain-analytics repo" % rel
    if any(path):
        line += " - section: " + " > ".join(p for p in path if p)
    return line + "\n> Synced from git. Edit the markdown file; an edit made here is replaced."


def body_for(rel, path, text):
    return "%s\n\n%s" % (breadcrumb(rel, path), text)


def plan_documents(only=None):
    """Every document the repo should produce, in a stable order."""
    docs = []
    for rel in tracked_markdown(only):
        text = read_text(rel)
        if not text.strip():
            continue
        seen = Counter()
        for section in sections(text):
            for path, body in section_documents(section["nodes"]):
                key = "/".join(p for p in path if p)
                seen[key] += 1
                nth = seen[key]
                if nth > 1:                # two headings with the same name in one file
                    key = "%s#%d" % (key, nth)
                    path = path + ["(%d)" % nth]
                digest = hashlib.sha1(("%s#%s" % (rel, key)).encode("utf-8")).hexdigest()[:24]
                docs.append({
                    "id": ID_PREFIX + digest,
                    "title": title_for(rel, path),
                    "folder": kb_store.normalize_folder(folder_for(rel)),
                    "body": body_for(rel, path, body),
                    "rel": rel,
                })
    return docs


# --- the sync ------------------------------------------------------------------------------------

def read_existing(workers=16):
    """Every document this script owns, read in parallel.

    A manifest would make a no-op run one GET instead of a thousand, and it is deliberately not used:
    a manifest cannot see an edit made in the Explorer, and the repo winning over such an edit - and
    keeping it in the revision trail - is the behaviour this sync promises.
    """
    ids = [i for i in kb_store.list_doc_ids() if i.startswith(ID_PREFIX)]
    if not ids:
        return {}
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for doc_id, doc in zip(ids, pool.map(kb_store.read_doc, ids)):
            if doc:
                out[doc_id] = doc
    return out


def classify(desired, existing, *, embed=True):
    """-> (create, update, unchanged, delete). Nothing is written here.

    🔴 `embed_error` MEANS "RETRY ME", BUT ONLY IF WE ARE EMBEDDING. A document Vertex could not
    vectorise is searchable by keyword and says so, and re-offering it every run is how it
    eventually gets its vectors. Under --no-embed every document carries that marker BY REQUEST, so
    reading it as dirty there makes a no-op run rewrite the entire library, for ever.
    """
    create, update, unchanged = [], [], []
    for want in desired:
        have = existing.get(want["id"])
        if have is None:
            create.append(want)
            continue
        same_text = (have.get("title") == want["title"]
                     and have.get("body") == want["body"]
                     and have.get("indexed_hash") == kb_chunk.content_hash(want["title"],
                                                                           want["body"]))
        needs_vectors = embed and bool(have.get("embed_error"))
        if same_text and have.get("folder") == want["folder"] and not needs_vectors \
                and not have.get("archived"):
            unchanged.append(want)
        else:
            update.append(want)
    wanted_ids = {d["id"] for d in desired}
    delete = sorted(i for i in existing if i not in wanted_ids)
    return create, update, unchanged, delete


def apply_document(want, have, *, embed):
    """Create or update one document through the Explorer's own write path."""
    if have is None:
        doc = kb_store.make_doc(doc_id=want["id"], title=want["title"], body=want["body"],
                                folder=want["folder"], kind=KIND, source=SOURCE, owner=OWNER)
    else:
        doc = have
        text_changed = (doc.get("title") != want["title"] or doc.get("body") != want["body"])
        # 🔴 A HUMAN EDIT IS KEPT BEFORE IT IS OVERWRITTEN. Only then: a revision per sync would
        # store a full body copy for history git already holds, forty deep, per document.
        if text_changed and doc.get("updated_by") and doc.get("updated_by") != OWNER:
            kb_store.push_revision(doc, by=OWNER, via="human",
                                   note="replaced by the current text of %s" % want["rel"])
        doc["title"] = want["title"]
        doc["body"] = want["body"]
        doc["folder"] = want["folder"]
        doc["kind"] = KIND
        doc["archived"] = False
        doc["updated_at"] = kb_store.now()
        doc["updated_by"] = OWNER
    return doc, kb_index.reindex_document(doc, embed=embed)


def run(args):
    started = time.monotonic()
    desired = plan_documents(args.only)
    if not desired:
        raise SystemExit("No markdown matched. Check --only.")

    files = len({d["rel"] for d in desired})
    print("Repo:      %s" % REPO)
    print("Bucket:    gs://%s/%s/" % (kb_store.bucket_name(), kb_store.PREFIX))
    print("Folder:    %s" % TOP_FOLDER)
    print("Embedding: %s" % ("off (keyword only)" if not args.embed else
                             ("%s in %s" % (kb_embed.model_name(), kb_embed.location())
                              if kb_embed.enabled() else "UNAVAILABLE - no Vertex project resolved")))
    print("Planned:   %d documents from %d markdown files" % (len(desired), files))

    if args.plan_only:
        for doc in desired:
            print("  %-7d %s" % (len(doc["body"]), doc["title"]))
        return 0

    try:
        existing = read_existing(args.workers)
    except Exception as exc:                          # noqa: BLE001 - one specific, common cause
        # Never report an auth failure as something to try again (the repo-wide rule). The two
        # credentials expire independently and a raw RefreshError traceback names neither.
        raise SystemExit(
            "Could not read gs://%s/%s/: %s\n\n"
            "If that is a credentials error, this needs APPLICATION DEFAULT credentials, which are\n"
            "separate from the gcloud CLI login and expire on their own:\n"
            "    gcloud auth application-default login\n"
            "Retrying without re-authenticating cannot fix it."
            % (kb_store.bucket_name(), kb_store.PREFIX, str(exc)[:300]))
    create, update, unchanged, delete = classify(desired, existing, embed=args.embed)
    print("Live now:  %d documents this sync owns" % len(existing))
    print("Change:    %d new, %d updated, %d unchanged, %d to remove"
          % (len(create), len(update), len(unchanged), len(delete)))
    for doc in create[:args.show]:
        print("  + %s" % doc["title"])
    if len(create) > args.show:
        print("  + ... %d more" % (len(create) - args.show))
    for doc in update[:args.show]:
        print("  ~ %s" % doc["title"])
    if len(update) > args.show:
        print("  ~ ... %d more" % (len(update) - args.show))
    for doc_id in delete[:args.show]:
        print("  - %s  (%s)" % (doc_id, (existing[doc_id].get("title") or "")[:90]))
    if len(delete) > args.show:
        print("  - ... %d more" % (len(delete) - args.show))

    if args.dry_run:
        print("\nDRY RUN - nothing was written.")
        return 0
    if not (create or update or delete):
        print("\nAlready in sync. Nothing written. (%.1fs)" % (time.monotonic() - started))
        return 0
    if not args.yes:
        raise SystemExit("\nRefusing to write without --yes (or --dry-run to see the plan).")

    written, keyword_only, failed = 0, [], []
    for want in create + update:
        try:
            _, report = apply_document(want, existing.get(want["id"]), embed=args.embed)
        except Exception as exc:                      # noqa: BLE001 - one document must not end the run
            failed.append((want["title"], str(exc)[:200]))
            continue
        written += 1
        if args.embed and not report.get("semantic"):
            keyword_only.append((want["title"], report.get("error") or "no reason given"))
        if written % 25 == 0:
            print("  ... %d/%d" % (written, len(create) + len(update)))

    removed = 0
    for doc_id in delete:
        if not doc_id.startswith(ID_PREFIX):          # belt and braces; classify cannot produce one
            continue
        if kb_store.delete_doc(doc_id):
            removed += 1

    # 🔴 `kb_index.refresh_manifest()` IS DELIBERATELY NOT CALLED. It rebuilds the whole corpus in
    # memory - one GET per document, embeddings included - to update counters on one page, and the
    # live service does not depend on it: freshness comes from the object listing
    # (`kb_store.chunk_signature`), so the library is current the moment these writes land.

    print("\nWrote %d documents, removed %d, in %.1fs." % (written, removed,
                                                           time.monotonic() - started))
    if keyword_only:
        print("KEYWORD ONLY - no vectors for %d document(s); the next run retries them:"
              % len(keyword_only))
        for title, why in keyword_only[:10]:
            print("  ! %s  (%s)" % (title, why))
    if failed:
        print("FAILED %d document(s):" % len(failed))
        for title, why in failed:
            print("  x %s  (%s)" % (title, why))
        return 1
    return 0


def main(argv=None):
    # 🔴 THE REPORT NAMES DOCUMENTS, AND THIS REPO'S HEADINGS CONTAIN ARROWS AND DASHES. A Windows
    # console is cp1252 by default, so printing one of those titles raises UnicodeEncodeError and
    # kills a run that had already written half the library.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                             # noqa: BLE001 - older Python, or a pipe
            pass

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dry-run", action="store_true", help="show the plan, write nothing")
    p.add_argument("--plan-only", action="store_true",
                   help="list the documents the repo produces without reading the bucket at all")
    p.add_argument("--yes", action="store_true", help="actually write")
    p.add_argument("--only", action="append",
                   help="limit to paths matching this glob (repeatable), e.g. --only 'md/*.md'")
    p.add_argument("--no-embed", dest="embed", action="store_false",
                   help="index by keyword only; a later run adds the vectors")
    p.add_argument("--workers", type=int, default=16, help="parallel reads of existing documents")
    p.add_argument("--show", type=int, default=12, help="how many changes to name in the report")
    p.add_argument("--bucket", default="", help="override GCS_BUCKET")
    p.add_argument("--prefix", default="", help="override KB_PREFIX, e.g. kb-dev for a rehearsal")
    args = p.parse_args(argv)
    if args.bucket:
        os.environ["GCS_BUCKET"] = args.bucket
    if args.prefix:
        os.environ["KB_PREFIX"] = args.prefix
        kb_store.PREFIX = args.prefix.strip("/")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
