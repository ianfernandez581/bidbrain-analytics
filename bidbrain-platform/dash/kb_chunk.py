"""kb_chunk.py - text into retrievable passages, and the ONE tokenizer the whole knowledge base uses.

CHUNK SIZE IS A COMPROMISE BETWEEN TWO FAILURES. Too small and a passage carries a claim without
the reasoning that makes it true; too large and a hit is not quotable and its embedding averages
several subjects into a vector that is about none of them. ~220 words is about a paragraph of
prose, and the 40-word overlap is what keeps a point that straddles a boundary findable as one
passage instead of two half-thoughts.

🔴 STRUCTURE FIRST, NOT A FIXED WORD WINDOW. These are written documents: media plans, briefs,
meeting notes. A bullet retrieved without its heading, or half a numbered step, reads authoritative
and means nothing. So whole blocks (paragraphs, bullets, headings) are packed up to the budget and
only a block that is on its own larger than the budget is ever cut.

🔴 THE OVERLAP IS PENDING UNTIL A REAL BLOCK FOLLOWS IT. Seeding the next chunk with the previous
chunk's tail eagerly means any document that ends on a chunk boundary, which is every document
shorter than the budget, emits a final chunk consisting of nothing but that tail: a duplicate of
text already indexed, costing a second embedding call and able to occupy both of the two result
slots a document gets.

ONE TOKENIZER. BM25 in kb_index.py tokenizes the corpus and the query, and both must agree
exactly or a term that exists cannot be found. It lives here, with the chunker, so there is one
definition of what a word is.
"""
import hashlib
import re

CHUNK_WORDS = 220
CHUNK_OVERLAP = 40

# Deliberately tiny. An aggressive stopword list strips the very words that make a media question
# specific ("how", "when", "why"). These carry no retrieval signal at all.
_STOP = frozenset("""
a an and are as at be been but by for from had has have i if in into is it its of on or s t that
the their then there these they this to was were what which who will with you your
""".split())

_WORD = re.compile(r"[a-z0-9']+")


def tokenize(text):
    """Lowercase word tokens, stopwords and one-character noise dropped."""
    return [w for w in _WORD.findall((text or "").lower()) if len(w) > 1 and w not in _STOP]


def _blocks(text):
    """Split on blank lines: paragraphs, list items, headings."""
    return [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]


def chunk_text(text):
    """Pack a document into retrievable passages. See the module header for both rules."""
    out = []
    current = []            # the blocks making up the chunk being built
    count = 0
    pending_tail = ""       # overlap from the previous chunk; used only if a block follows

    def emit():
        nonlocal current, count, pending_tail
        if not current:
            return
        chunk = "\n\n".join(current).strip()
        if chunk:
            out.append(chunk)
        pending_tail = (" ".join(" ".join(current).split()[-CHUNK_OVERLAP:])
                        if CHUNK_OVERLAP else "")
        current, count = [], 0

    for block in _blocks(text):
        words = block.split()
        if len(words) > CHUNK_WORDS:
            # An oversized block (a wall of pasted text with no paragraph breaks) is the one case
            # that must be cut mid-block. The windows overlap each other, so no tail is carried
            # across them.
            emit()
            step = max(1, CHUNK_WORDS - CHUNK_OVERLAP)
            for start in range(0, len(words), step):
                window = words[start:start + CHUNK_WORDS]
                if not window:
                    break
                out.append(" ".join(window))
                if start + CHUNK_WORDS >= len(words):
                    break
            pending_tail = " ".join(words[-CHUNK_OVERLAP:]) if CHUNK_OVERLAP else ""
            continue
        if count + len(words) > CHUNK_WORDS:
            emit()
        if not current and pending_tail:
            current.append(pending_tail)
            count += len(pending_tail.split())
            pending_tail = ""
        current.append(block)
        count += len(words)
    emit()                  # whatever is left is real blocks, never a bare tail
    return [c for c in out if c.strip()]


def content_hash(title, body):
    """What the stored chunks were built FROM.

    🔴 A HASH, NEVER A TIMESTAMP. An edit and a re-index can land in the same second, and restoring
    an older revision makes `updated_at` newer while the text goes back to something already
    indexed. Only the content answers "are these chunks the current text".
    """
    h = hashlib.sha256()
    h.update((title or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((body or "").encode("utf-8"))
    return h.hexdigest()
