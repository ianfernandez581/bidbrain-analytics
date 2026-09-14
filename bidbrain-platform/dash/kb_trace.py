"""kb_trace.py - what the retriever actually did, span by span, readable in Arize Phoenix.

WHY. A search fuses two retrievers by rank and hands eight passages to a model, and from outside
the only visible thing is the eight passages. Every interesting question about it is a TREE, not a
line: did the semantic half run at all, or did Vertex quietly fail and leave us on wording? Which
retriever found the passage that got used? Did fusion promote something neither list had near its
top, which is the entire reason hybrid search exists? A log line cannot answer those. Spans can,
and Phoenix is built to read LLM and retrieval span trees specifically.

🔴 OFF UNLESS `PHOENIX_COLLECTOR_ENDPOINT` IS SET, AND A NO-OP WHEN OFF. Not a fast path: a
`_NullSpan` whose methods do nothing. The call sites are on the critical path of every search, and
they must read identically whether tracing is on or off.

🔴 NOTHING HERE MAY EVER RAISE INTO A REQUEST. Observability that breaks the thing it observes
turns "I cannot see why search is slow" into "search is down". Every public function is wrapped,
configuration swallows its own failure and records the reason for the Observability page, and a
failing exporter degrades to dropped spans.

🔴 PHOENIX'S OTLP/HTTP ENDPOINT IS PROTOBUF ONLY. Posting the same payload as OTLP/JSON, which the
spec defines and several collectors accept, gets a flat `415 Unsupported content type:
application/json`. That is why this encodes with `opentelemetry-exporter-otlp-proto-common` rather
than hand-rolling a JSON body.

🔴 AND YET NO NEW HTTP STACK. The obvious dependency, `opentelemetry-exporter-otlp-proto-http`,
drags in its own transport. We take only the ENCODER half, which has no transport, and post its
bytes with `requests`, which this image already has. That is `_post` below, and it is the whole
difference.

🔴 A RETRIEVER SPAN CARRIES THE PASSAGES IT RETURNED, which is internal company writing. Whatever
Phoenix this points at therefore holds that prose and must be access controlled like the platform
itself. `KB_TRACE_CONTENT=off` turns passage capture off entirely for a Phoenix somebody else can
read.
"""
import logging
import os
import threading
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

# OpenInference semantic conventions: the attribute names Phoenix keys on to classify a span and
# unflatten its documents. Spelled out rather than imported from a third package whose entire
# content is these strings. A wrong string fails SILENTLY: the span still arrives, it is just
# classified UNKNOWN and its documents render as loose attributes.
SPAN_KIND = "openinference.span.kind"
INPUT_VALUE = "input.value"
OUTPUT_VALUE = "output.value"
DOC_PREFIX = "retrieval.documents"

CHAIN, RETRIEVER, EMBEDDING, LLM = "CHAIN", "RETRIEVER", "EMBEDDING", "LLM"

MAX_FIELD_CHARS = 2_000
MAX_DOCS_WITH_CONTENT = 12

_state = {"on": False, "reason": "not configured", "endpoint": "", "provider": None,
          "started": False}
_lock = threading.Lock()


def endpoint():
    return (os.environ.get("PHOENIX_COLLECTOR_ENDPOINT") or "").strip().rstrip("/")


def capture_content():
    return (os.environ.get("KB_TRACE_CONTENT", "on").strip().lower()
            not in ("off", "0", "false", "no"))


def status():
    """What the Observability page prints. Always safe to call."""
    return {"enabled": _state["on"], "reason": _state["reason"], "endpoint": _state["endpoint"],
            "capture_content": capture_content(),
            "how": ("Set PHOENIX_COLLECTOR_ENDPOINT on the platform service to a Phoenix "
                    "collector, then redeploy. Nothing else changes: with it unset every span "
                    "here is a no-op.")}


def configure():
    """Turn tracing on if it is configured. Idempotent, and it never raises."""
    with _lock:
        if _state["started"]:
            return status()
        _state["started"] = True
        ep = endpoint()
        if not ep:
            _state["reason"] = "PHOENIX_COLLECTOR_ENDPOINT is not set"
            return status()
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
        except ImportError as exc:
            _state["reason"] = ("the OpenTelemetry packages are not in this image (%s). Add "
                                "opentelemetry-sdk and opentelemetry-exporter-otlp-proto-common "
                                "to requirements.txt and redeploy." % exc)
            return status()

        import requests

        class _UrllibOTLPSpanExporter(SpanExporter):
            """The encoder half of the official exporter, posted with the HTTP client this image
            already has. Protobuf, because Phoenix refuses JSON."""

            def __init__(self, url):
                self.url = url

            def export(self, spans):
                try:
                    body = encode_spans(spans).SerializeToString()
                    r = requests.post(self.url, data=body, timeout=10,
                                      headers={"Content-Type": "application/x-protobuf"})
                    if r.status_code >= 300:
                        log.warning("kb_trace: collector answered %s: %s", r.status_code,
                                    r.text[:200])
                        return SpanExportResult.FAILURE
                except Exception:                  # noqa: BLE001 - a dropped span, never an error
                    log.debug("kb_trace: export failed", exc_info=True)
                    return SpanExportResult.FAILURE
                return SpanExportResult.SUCCESS

            def shutdown(self):
                return None

        try:
            provider = TracerProvider(resource=Resource.create({"service.name": "bidbrain-kb"}))
            provider.add_span_processor(
                BatchSpanProcessor(_UrllibOTLPSpanExporter(ep + "/v1/traces")))
            _state["provider"] = provider
            _state["on"] = True
            _state["endpoint"] = ep
            _state["reason"] = "sending spans to " + ep
        except Exception as exc:                   # noqa: BLE001
            _state["reason"] = "could not start tracing (%s)" % type(exc).__name__
        return status()


class _NullSpan:
    def set(self, **kw):
        return self

    def input(self, v):
        return self

    def output(self, v):
        return self

    def documents(self, rows, meta_keys=()):
        return self

    def error(self, msg):
        return self


_NULL = _NullSpan()


class _Span:
    def __init__(self, span):
        self._s = span

    def _put(self, k, v):
        if v is None:
            return
        if isinstance(v, (bool, int, float)):
            self._s.set_attribute(k, v)
        else:
            self._s.set_attribute(k, str(v)[:MAX_FIELD_CHARS])

    def set(self, **kw):
        for k, v in kw.items():
            self._put(k.replace("__", "."), v)
        return self

    def input(self, v):
        self._put(INPUT_VALUE, v)
        return self

    def output(self, v):
        self._put(OUTPUT_VALUE, v)
        return self

    def documents(self, rows, meta_keys=()):
        """The flattened list Phoenix rebuilds into a ranked table.

        🔴 IN RETURNED ORDER, which is what makes the trace true: Phoenix reads the index as the
        rank. Sorting this for display would draw a ranking that never happened and it would look
        entirely healthy.
        """
        keep = capture_content()
        for i, r in enumerate(rows):
            base = "%s.%d.document." % (DOC_PREFIX, i)
            self._put(base + "id", r.get("document_id"))
            self._put(base + "score", r.get("score"))
            if keep and i < MAX_DOCS_WITH_CONTENT:
                self._put(base + "content", r.get("passage"))
            meta = {k: r.get(k) for k in meta_keys if r.get(k) is not None}
            if meta:
                import json
                self._put(base + "metadata", json.dumps(meta, default=str))
        return self

    def error(self, msg):
        try:
            self._s.set_status(__import__("opentelemetry.trace", fromlist=["Status"]).Status(
                __import__("opentelemetry.trace", fromlist=["StatusCode"]).StatusCode.ERROR,
                str(msg)[:300]))
        except Exception:                          # noqa: BLE001
            pass
        return self


@contextmanager
def span(name, kind=CHAIN, **attrs):
    """One span, or a no-op. Never raises, whatever happens inside tracing itself."""
    if not _state["on"] or not _state["provider"]:
        yield _NULL
        return
    try:
        tracer = _state["provider"].get_tracer("bidbrain-kb")
        with tracer.start_as_current_span(name) as raw:
            s = _Span(raw)
            s.set(**{SPAN_KIND: kind})
            s.set(**attrs)
            yield s
    except Exception:                              # noqa: BLE001
        log.debug("kb_trace: span failed", exc_info=True)
        yield _NULL


def ui_url():
    """Phoenix's own UI, when the collector endpoint also serves it. Rendered in an iframe on the
    Observability page, same origin through the platform, so it sits behind our gate rather than
    being a second thing to secure."""
    ep = endpoint()
    return ep or ""


# --- the local trace record ------------------------------------------------------------------
# Phoenix is optional; this is not. Every question already writes an activity record carrying its
# scope, latency, passage count, model and the documents that came back (kb_activity.py), so the
# page can answer "why did it say that" for a question asked five minutes ago even with tracing
# switched off and even when another instance served it. An in-process ring buffer could not: the
# instance that answered is rarely the one serving the page.

def recent_questions(limit=50):
    import kb_activity
    rows = [e for e in kb_activity.recent() if e.get("kind") in ("question", "search")]
    return list(reversed(rows))[:limit]


def now_ms():
    return int(time.time() * 1000)
