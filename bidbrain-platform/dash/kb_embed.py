"""kb_embed.py - text into vectors, via Vertex AI. The SEMANTIC half of the knowledge base.

WHY IT EXISTS. Keyword search only finds a passage that shares WORDS with the question. Ask "how
do we decide what to charge a new account?" and a note titled "Rate card rationale" scores zero,
because it says rate and pricing where the question says charge and cost. Embeddings put both in
the same space, so the note is found by MEANING. Neither method wins outright, which is why
kb_index.py runs both and fuses the ranks.

🔴 QUERY AND DOCUMENT EMBEDDINGS ARE NOT THE SAME CALL. Google's retrieval models are trained
asymmetrically: text being STORED goes in as `RETRIEVAL_DOCUMENT` (with its title, which measurably
helps), text being SEARCHED FOR goes in as `RETRIEVAL_QUERY`. Using one task type for both is the
commonest way to build a semantic search that works and ranks quietly worse than it should, and it
fails SILENTLY: every call still returns a perfectly well-formed vector. `embed_documents` and
`embed_query` stay two functions precisely so the distinction cannot be lost.

🔴 FAIL SOFT, AND SAY SO. No credentials, a quota wall, a bad region -> `(None, reason)`. The
caller stores the reason, search degrades to keyword-only, and the payload carries
`semantic: false` plus the reason so the UI can print "searched by keyword only". A retrieval gap
that is not declared reads to a person as "there is nothing about that", which is a lie.

TRANSPORT. Vertex `:predict` over stdlib `urllib`, with a token from `google.auth.default()`.
That resolves to the Cloud Run runtime service account in production and to a developer's
application-default credentials on a laptop, so the identical code path is testable locally.
`google-auth` is already in this image. The runtime SA needs `roles/aiplatform.user`.

🔴 A WRONG REGION DOES NOT ERROR USEFULLY, it 404s the publisher path. If this starts returning
"Vertex answered 404" after nothing changed but a region, that is what happened.
"""
import array
import base64
import json
import logging
import math
import os
import sys
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

MODEL = os.environ.get("KB_EMBED_MODEL", "text-embedding-005").strip()
# Region rule for this estate: australia-southeast1, everywhere, always. Overridable ONLY because
# a region can lose capacity for a model.
LOCATION = os.environ.get("KB_VERTEX_LOCATION", "australia-southeast1").strip()
PROJECT = (os.environ.get("KB_VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()

# Vertex accepts up to 250 instances per predict call, but a batch that big is one slow request
# whose failure loses everything in it. 32 chunks (~7k words) keeps a retry cheap.
# 🔴 A COUNT, NOT A TOKEN BUDGET: the model also caps a REQUEST at 20k tokens, and 32 dense
# passages can cross that. `_predict_split` halves a batch the model refuses, so this number never
# has to be conservative enough for the worst document.
BATCH = 32

# Each instance is capped by the model (2048 input tokens). Our chunks are ~220 words, so this
# ceiling exists only to stop one pathological "word" (a minified blob pasted into a note) from
# failing the whole batch.
MAX_CHARS_PER_INSTANCE = 8_000

_RETRY_WAITS = (2.0, 6.0)       # seconds before retrying a 429 or a 5xx
_TIMEOUT = 60

_token_cache = {"value": "", "expires": 0.0}
_creds = None


def model_name():
    return MODEL


def location():
    return LOCATION


def enabled():
    """Whether a semantic call is worth attempting at all.

    `KB_EMBED=off` is the switch that proves the degraded path: with it set the whole system must
    still answer, on keyword alone, and say so on screen."""
    if os.environ.get("KB_EMBED", "").strip().lower() in ("off", "0", "false", "no"):
        return False
    return bool(_project())


def _project():
    global PROJECT
    if PROJECT:
        return PROJECT
    try:
        import google.auth
        _, proj = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        PROJECT = (proj or "").strip()
    except Exception:                               # noqa: BLE001
        PROJECT = ""
    return PROJECT


def _token():
    """A Vertex access token. Cached until a minute before it expires."""
    global _creds
    now = time.time()
    if _token_cache["value"] and _token_cache["expires"] > now + 60:
        return _token_cache["value"]
    import google.auth
    import google.auth.transport.requests
    if _creds is None:
        _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    _creds.refresh(google.auth.transport.requests.Request())
    _token_cache["value"] = _creds.token or ""
    exp = getattr(_creds, "expiry", None)
    _token_cache["expires"] = exp.timestamp() if exp else now + 1800
    return _token_cache["value"]


def _predict(instances):
    """One Vertex :predict call. Module level so a test can replace it without a network."""
    if not enabled():
        return None, "Vertex embeddings are switched off for this deployment"
    try:
        token = _token()
    except Exception as exc:                        # noqa: BLE001
        return None, "could not get GCP credentials for Vertex (%s)" % type(exc).__name__
    loc = LOCATION
    host = "aiplatform.googleapis.com" if loc == "global" else f"{loc}-aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{_project()}/locations/{loc}"
           f"/publishers/google/models/{MODEL}:predict")
    payload = json.dumps({"instances": instances}).encode("utf-8")
    # A 429 or a 5xx is retried, briefly. Indexing a library hits the per-minute quota as a matter
    # of course, and all-or-nothing per document means one blip throws away the earlier batches of
    # a long document. Two short waits absorb the normal burst; anything longer still fails soft.
    data = None
    for wait in _RETRY_WAITS + (None,):
        req = urllib.request.Request(url, data=payload, method="POST",
                                     headers={"Authorization": "Bearer " + token,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:      # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            if wait is not None and (exc.code == 429 or exc.code >= 500):
                log.warning("kb_embed: Vertex answered %s, retrying in %.0fs", exc.code, wait)
                time.sleep(wait)
                continue
            return None, f"Vertex answered {exc.code}: {body}"
        except Exception as exc:                    # noqa: BLE001
            return None, "could not reach Vertex AI (%s)" % type(exc).__name__
    try:
        out = [p["embeddings"]["values"] for p in data["predictions"]]
    except Exception:                               # noqa: BLE001
        return None, "Vertex returned an unexpected embedding response"
    if len(out) != len(instances):
        # Never pair a vector with the wrong text: a short answer would shift every embedding onto
        # its neighbour's chunk and the whole index would rank plausibly and wrongly.
        return None, f"Vertex returned {len(out)} embeddings for {len(instances)} inputs"
    return out, ""


_TOKEN_LIMIT_HINTS = ("input token count", "token count is", "supports up to")


def _predict_split(instances):
    """`_predict`, but a batch the model refuses as TOO MANY TOKENS is halved and retried. Halving
    costs one wasted call on a rare dense batch and never silently drops a document; a single
    instance still too big is a real refusal and is reported as one."""
    vecs, err = _predict(instances)
    if vecs is not None or len(instances) < 2 or not any(h in err for h in _TOKEN_LIMIT_HINTS):
        return vecs, err
    half = len(instances) // 2
    left, err = _predict_split(instances[:half])
    if left is None:
        return None, err
    right, err = _predict_split(instances[half:])
    if right is None:
        return None, err
    return left + right, ""


def embed_documents(texts, title=""):
    """Vectors for text being STORED: `RETRIEVAL_DOCUMENT`, plus the document title.

    All or nothing per document. A partial batch would leave a document half-searchable with
    nothing recording which half, so any failure returns `(None, reason)` and the caller marks the
    whole document keyword-only until the next index attempt.
    """
    if not texts:
        return [], ""
    out = []
    for start in range(0, len(texts), BATCH):
        instances = []
        for text in texts[start:start + BATCH]:
            inst = {"task_type": "RETRIEVAL_DOCUMENT", "content": (text or "")[:MAX_CHARS_PER_INSTANCE]}
            # The title is a real ranking signal for RETRIEVAL_DOCUMENT, and it is also how a chunk
            # carries its own document's subject: a body rarely names its own topic.
            if title:
                inst["title"] = title[:500]
            instances.append(inst)
        vecs, err = _predict_split(instances)
        if vecs is None:
            return None, err
        out.extend(vecs)
    return [normalize(v) for v in out], ""


def embed_query(text):
    """The vector for a SEARCH string. `RETRIEVAL_QUERY`, no title. See the module header."""
    q = (text or "").strip()
    if not q:
        return None, "empty query"
    vecs, err = _predict([{"task_type": "RETRIEVAL_QUERY", "content": q[:MAX_CHARS_PER_INSTANCE]}])
    if vecs is None:
        return None, err
    return normalize(vecs[0]), ""


# --- storage and arithmetic --------------------------------------------------------------------
# Vectors are stored NORMALISED (unit length), which makes cosine similarity a plain dot product
# at query time: no per-comparison square roots over thousands of chunks.

def normalize(vec):
    mag = math.sqrt(sum(x * x for x in vec))
    if mag <= 0:
        return list(vec)
    return [x / mag for x in vec]


def pack(vec):
    """float list -> base64 of little-endian float32. ~4 KB for 768 dims, against ~9 KB as JSON."""
    arr = array.array("f", vec)
    # Forced little-endian so a vector written on one architecture reads back on another. In
    # practice everything here is x86-64, but the index would corrupt SILENTLY if that changed.
    if sys.byteorder != "little":
        arr.byteswap()
    return base64.b64encode(arr.tobytes()).decode("ascii")


def unpack(blob):
    """base64 float32 -> float list. Returns [] for empty or corrupt input rather than raising:
    one bad row must degrade that chunk's ranking, never break the whole search."""
    if not blob:
        return []
    try:
        raw = base64.b64decode(blob)
        arr = array.array("f")
        arr.frombytes(raw)
        if sys.byteorder != "little":
            arr.byteswap()
        return list(arr)
    except Exception:                               # noqa: BLE001
        return []


def probe():
    """One real embedding call. The post-deploy check that the credentials work, the region serves
    this model, and the SA has aiplatform.user."""
    if not enabled():
        return {"ok": False, "detail": "not configured", "model": MODEL, "region": LOCATION}
    started = time.monotonic()
    vec, err = embed_query("knowledge base reachability probe")
    ms = int((time.monotonic() - started) * 1000)
    if vec is None:
        return {"ok": False, "detail": err, "model": MODEL, "region": LOCATION,
                "project": _project(), "ms": ms}
    return {"ok": True, "dims": len(vec), "model": MODEL, "region": LOCATION,
            "project": _project(), "ms": ms}
