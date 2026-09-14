"""kb_chat.py - the model call behind the Ask panel. Kimi first, Gemini named as the fallback.

ONE INTERFACE OVER TWO WIRE FORMATS. `stream(...)` yields `(kind, payload)` events - "token",
"usage", "done" - whichever model answered. The route never learns which JSON shape a chunk arrived
in, and the panel is told WHICH MODEL replied so a fallback is visible rather than silent.

🔴 THE KIMI CODE KEY ONLY WORKS AGAINST `https://api.kimi.com/coding/v1`. Pointed at
`api.moonshot.ai` it returns 401, which looks exactly like a revoked key and has cost real debugging
time elsewhere in the estate. `KIMI_BASE_URL` exists so a plan change is an env var, not a deploy.

🔴 AN EXPLICIT `User-Agent`. Provider WAF rules commonly refuse a default library agent, and a
refusal at that layer arrives as a bare 403 with no useful body.

🔴 FALL BACK ONLY BEFORE THE FIRST TOKEN. Once text has been streamed to the browser, swapping
models mid-answer would splice two different replies together and the reader would have no way to
tell. `pre_stream` is the whole reason the error carries that flag.

`requests` is used rather than stdlib urllib, unlike the system this is ported from: that service
deliberately has no `requests` dependency to protect, and this one has shipped with it since the
feedback pipeline. `iter_lines` over a streamed response IS an SSE client.
"""
import json
import logging
import os
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = "bidbrain-kb-assistant/1.0"

KIMI = "kimi"
GEMINI = "gemini"
LABELS = {KIMI: "Kimi", GEMINI: "Gemini"}

KIMI_BASE = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1").rstrip("/")
KIMI_MODEL = os.environ.get("KB_KIMI_MODEL", "k3")
GEMINI_MODEL = os.environ.get("KB_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "{model}:streamGenerateContent?alt=sse")

TIMEOUT = (20, 180)              # (connect, read); a long read is normal while tokens stream
MAX_OUTPUT_TOKENS = 2048


class ProviderError(Exception):
    """A model refused or failed. `pre_stream` is True when no token had been produced yet, which
    is the only moment another model may be tried without changing an answer mid-reply."""

    def __init__(self, provider, message, *, status=None, body="", pre_stream=True):
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.body = body
        self.pre_stream = pre_stream


def configured(provider):
    if provider == KIMI:
        return bool((os.environ.get("KIMI_API_KEY") or "").strip())
    if provider == GEMINI:
        return bool((os.environ.get("GEMINI_API_KEY") or "").strip())
    return False


def available():
    """Which providers this deployment could actually use, best first."""
    return [p for p in (KIMI, GEMINI) if configured(p)]


def model_of(provider):
    return KIMI_MODEL if provider == KIMI else GEMINI_MODEL


# --- Kimi (OpenAI compatible) --------------------------------------------------------------------

def _kimi(prefix, messages):
    key = (os.environ.get("KIMI_API_KEY") or "").strip()
    if not key:
        raise ProviderError(KIMI, "Kimi is not configured for this deployment")
    body = {
        "model": KIMI_MODEL,
        "messages": [{"role": "system", "content": prefix}] + messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": MAX_OUTPUT_TOKENS,
        # 🔴 Omitting this is NOT neutral: the family defaults reasoning ON, which spends tokens
        # and time on a retrieval answer that does not need it. Only an explicit off disables it.
        "thinking": {"type": "disabled"},
    }
    # 🔴 NO `temperature` FIELD, DELIBERATELY. `k3` accepts exactly one value and rejects every
    # other with `400 invalid temperature: only 0.6 is allowed for this model` - including the 0.2
    # that is right for a retrieval assistant everywhere else. Sending 0.6 explicitly would pin us
    # to today's only legal value and break again if a later model pins a different one, so the
    # provider's own default is taken. Verified against api.kimi.com/coding/v1 on 2026-09-14; it is
    # why the first live turn silently fell through to Gemini.
    try:
        r = requests.post(KIMI_BASE + "/chat/completions", json=body, stream=True, timeout=TIMEOUT,
                          headers={"Authorization": "Bearer " + key, "User-Agent": USER_AGENT,
                                   "Accept": "text/event-stream"})
    except Exception as exc:                       # noqa: BLE001
        raise ProviderError(KIMI, "could not reach Kimi (%s)" % type(exc).__name__) from exc
    if r.status_code != 200:
        detail = r.text[:600]
        r.close()
        hint = ""
        if r.status_code == 401 and "moonshot" in KIMI_BASE:
            hint = (" (the coding key only works against api.kimi.com/coding/v1, so a 401 here "
                    "usually means the base URL, not the key)")
        raise ProviderError(KIMI, "Kimi answered %d%s" % (r.status_code, hint),
                            status=r.status_code, body=detail)
    sent = False
    try:
        for line in r.iter_lines(decode_unicode=True):
            if line is None:
                continue
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except ValueError:
                continue
            if obj.get("error"):
                err = obj["error"] if isinstance(obj["error"], dict) else {"message": str(obj["error"])}
                raise ProviderError(KIMI, "Kimi stream error: %s" % str(err.get("message", ""))[:200],
                                    pre_stream=not sent)
            choice = (obj.get("choices") or [{}])[0] or {}
            delta = choice.get("delta") or {}
            if delta.get("content"):
                sent = True
                yield ("token", delta["content"])
            usage = obj.get("usage") or choice.get("usage")
            if usage:
                yield ("usage", {"tokens_in": usage.get("prompt_tokens"),
                                 "tokens_out": usage.get("completion_tokens")})
    finally:
        r.close()


# --- Gemini --------------------------------------------------------------------------------------

def _gemini(prefix, messages):
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise ProviderError(GEMINI, "Gemini is not configured for this deployment")
    contents = []
    for m in messages:
        contents.append({"role": "model" if m["role"] == "assistant" else "user",
                         "parts": [{"text": m["content"]}]})
    body = {
        "systemInstruction": {"parts": [{"text": prefix}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                             # Off: a retrieval answer does not need a reasoning budget, and the
                             # panel has nowhere to show it.
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    try:
        r = requests.post(GEMINI_ENDPOINT.format(model=GEMINI_MODEL), json=body, stream=True,
                          timeout=TIMEOUT,
                          headers={"x-goog-api-key": key, "User-Agent": USER_AGENT,
                                   "Accept": "text/event-stream"})
    except Exception as exc:                       # noqa: BLE001
        raise ProviderError(GEMINI, "could not reach Gemini (%s)" % type(exc).__name__) from exc
    if r.status_code != 200:
        detail = r.text[:600]
        r.close()
        raise ProviderError(GEMINI, "Gemini answered %d" % r.status_code, status=r.status_code,
                            body=detail)
    sent = False
    try:
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except ValueError:
                continue
            for cand in (obj.get("candidates") or []):
                for part in ((cand.get("content") or {}).get("parts") or []):
                    if part.get("text"):
                        sent = True
                        yield ("token", part["text"])
                if cand.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT"):
                    raise ProviderError(GEMINI, "Gemini stopped: %s" % cand["finishReason"],
                                        pre_stream=not sent)
            u = obj.get("usageMetadata") or {}
            if u:
                yield ("usage", {"tokens_in": u.get("promptTokenCount"),
                                 "tokens_out": u.get("candidatesTokenCount")})
    finally:
        r.close()


_IMPL = {KIMI: _kimi, GEMINI: _gemini}


def stream(prefix, messages, prefer=None):
    """Stream one answer. Yields ("model", name) first, then ("token", text)..., ("usage", {...}).

    Raises ProviderError only when EVERY available provider failed before its first token.
    """
    order = [p for p in ([prefer] if prefer else []) + available() if configured(p)]
    seen, ordered = set(), []
    for p in order:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    if not ordered:
        raise ProviderError("none", "No model is configured for this deployment. The knowledge "
                                    "base can still be searched; it cannot answer in prose.")
    last = None
    for i, provider in enumerate(ordered):
        started = time.monotonic()
        sent = False
        try:
            gen = _IMPL[provider](prefix, messages)
            for kind, payload in gen:
                if kind == "token" and not sent:
                    sent = True
                    # Announced at the FIRST token, not before: until one arrives this provider
                    # might still fail over, and a model name that then changes is a lie the
                    # reader already saw.
                    yield ("model", {"provider": provider, "label": LABELS[provider],
                                     "model": model_of(provider),
                                     "fallback": i > 0,
                                     "first_token_ms": int((time.monotonic() - started) * 1000)})
                yield (kind, payload)
            if sent:
                return
            # A clean stream that produced nothing is a failure, not an empty answer.
            last = ProviderError(provider, "%s returned no answer" % LABELS[provider])
        except ProviderError as exc:
            last = exc
            log.warning("kb_chat: %s failed (%s): %s", provider, exc.status, exc)
            if not exc.pre_stream:
                # 🔴 Text is already on the reader's screen. Another model now would splice two
                # different answers together with nothing to mark the seam.
                raise
        except Exception as exc:                   # noqa: BLE001
            last = ProviderError(provider, "%s failed (%s)" % (LABELS[provider], type(exc).__name__))
            log.exception("kb_chat: %s raised", provider)
    raise last


def probe(provider):
    """One tiny real call: does the key work, does the host accept our request, can this region
    reach it. The post-deploy check behind the Observability page."""
    if not configured(provider):
        return {"provider": provider, "ok": False, "detail": "not configured"}
    started = time.monotonic()
    got = []
    try:
        for kind, payload in _IMPL[provider]("Reply with the single word: ok.",
                                             [{"role": "user", "content": "ok"}]):
            if kind == "token":
                got.append(payload)
    except ProviderError as exc:
        return {"provider": provider, "ok": False, "model": model_of(provider),
                "status": exc.status, "detail": str(exc), "body": (exc.body or "")[:200]}
    except Exception as exc:                       # noqa: BLE001
        return {"provider": provider, "ok": False, "model": model_of(provider),
                "detail": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
    return {"provider": provider, "ok": True, "model": model_of(provider),
            "ms": int((time.monotonic() - started) * 1000), "reply": "".join(got)[:40]}
