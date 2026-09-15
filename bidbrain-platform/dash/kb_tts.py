"""kb_tts.py - Google Cloud Text-to-Speech, so the assistant can talk back.

TWO CLOUD ENGINES, AND THE BROWSER'S OWN VOICE IS STILL THE DEFAULT AND FREE. Nothing reaches this
module unless somebody picks a cloud engine in the assistant's settings; `speechSynthesis` never
touches the server.

    chirp3-hd     ~$30 per 1M characters      quickest to start (~1s). Best for conversation.
    gemini-flash  text + audio tokens         steerable, ~3s slower to start. Better for read-aloud.

A spoken reply runs ~250 characters, so well under a cent a turn. What keeps it there is the SPOKEN
STYLE rule in kb_prompt.py: loosen that and this bill scales with it.

🔴 THE RUNTIME SERVICE ACCOUNT NEEDS `roles/serviceusage.serviceUsageConsumer` ON THE PROJECT.
Cloud TTS has no IAM role of its own and refuses a caller that may not "use" the project, with a
403 that names neither. This is the single most likely reason a fresh deployment is silent.

🔴 RETURNS THE AUDIO BYTES, NEVER A URL. The panel plays them from a blob on our own origin, so
nothing here needs a `media-src` for a third-party host.

🔴 `prompt` IS GEMINI-ONLY. Sending a style to Chirp is a 400, not a no-op.
"""
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

ENDPOINT = "https://texttospeech.googleapis.com/v1/text:synthesize"
# Cloud TTS rejects input over 5,000 bytes; a spoken reply that long means something upstream broke.
MAX_CHARS = 5000
TIMEOUT = 30

VOICES = ("Aoede", "Charon", "Fenrir", "Kore", "Leda", "Orus", "Puck", "Zephyr")
DEFAULT_VOICE = "Aoede"
DEFAULT_ENGINE = "chirp3-hd"

ENGINES = {
    "chirp3-hd": {
        "label": "Chirp 3 HD",
        "note": "Most natural, and quickest to start speaking. Best for a conversation.",
        "voice_name": lambda v: "en-US-Chirp3-HD-%s" % v,
        "model_name": "",
        "stylable": False,
    },
    "gemini-flash": {
        "label": "Gemini Flash TTS",
        "note": "Steerable, but about three seconds slower to start. Better for reading a long "
                "answer aloud than for talking.",
        "voice_name": lambda v: v,
        "model_name": "gemini-2.5-flash-tts",
        "stylable": True,
    },
}

_token_cache = {"value": "", "expires": 0.0}
_creds = None
# 🔴 USER CREDENTIALS NEED A QUOTA PROJECT AND A SERVICE ACCOUNT DOES NOT. On Cloud Run this is
# empty and nothing changes. On a laptop under `gcloud auth application-default login`, Cloud TTS
# answers a flat 403 saying "requires a quota project, which is not set by default" until the
# project travels in `x-goog-user-project`. Without this the feature is untestable locally, which
# is the same as untested.
_quota_project = None


class TTSError(Exception):
    """A synthesis that produced no audio. The message is safe to show a person."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def enabled():
    return os.environ.get("KB_TTS", "").strip().lower() not in ("off", "0", "false", "no")


def catalog():
    """What the voice picker renders. Server-driven, so adding a voice is one edit here."""
    return {
        "voices": list(VOICES),
        "default_voice": DEFAULT_VOICE,
        "default_engine": DEFAULT_ENGINE,
        "enabled": enabled(),
        "engines": [{"id": k, "label": e["label"], "note": e["note"]} for k, e in ENGINES.items()],
    }


def _token():
    """The runtime service account's token. `google.auth.default()` for the same reason kb_embed
    uses it: the identical path works on a laptop under ADC and on Cloud Run."""
    global _creds, _quota_project
    now = time.time()
    if _token_cache["value"] and _token_cache["expires"] > now + 60:
        return _token_cache["value"]
    import google.auth
    import google.auth.transport.requests
    if _creds is None:
        _creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _quota_project = getattr(_creds, "quota_project_id", None)
    _creds.refresh(google.auth.transport.requests.Request())
    _token_cache["value"] = _creds.token or ""
    exp = getattr(_creds, "expiry", None)
    _token_cache["expires"] = exp.timestamp() if exp else now + 1800
    return _token_cache["value"]


def synthesize(text, engine=DEFAULT_ENGINE, voice="", style=""):
    """MP3 bytes for one utterance.

    Raises TTSError rather than returning silence: the panel falls back to the browser voice and
    SAYS it did, because a voice mode that simply goes quiet reads as broken where a plainer voice
    does not.
    """
    if not enabled():
        raise TTSError("Cloud voices are switched off for this deployment.", 503)
    cfg = ENGINES.get(engine)
    if not cfg:
        raise TTSError('Unknown voice engine "%s"' % engine, 400)
    said = (text or "").strip()
    if not said:
        raise TTSError("Nothing to speak", 400)
    if len(said) > MAX_CHARS:
        raise TTSError("Too long to speak (%d characters, limit %d)" % (len(said), MAX_CHARS), 413)
    # An unknown voice is a stale saved preference, not an error worth failing a reply over.
    name = voice if voice in VOICES else DEFAULT_VOICE

    body = {"input": {"text": said},
            "voice": {"languageCode": "en-US", "name": cfg["voice_name"](name)},
            "audioConfig": {"audioEncoding": "MP3"}}
    if cfg["model_name"]:
        body["voice"]["model_name"] = cfg["model_name"]
    if cfg["stylable"] and style:
        body["input"]["prompt"] = str(style)[:500]

    try:
        token = _token()
    except Exception as exc:                                   # noqa: BLE001
        raise TTSError("Text to speech is not available here (no service credentials: %s)."
                       % type(exc).__name__, 503)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if _quota_project:
        headers["x-goog-user-project"] = _quota_project
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:      # noqa: S310 - fixed URL
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message") or detail
        except ValueError:
            pass
        # 🔴 Google's own sentence is the useful part: "API not enabled", "permission denied" (the
        # serviceUsageConsumer grant), a quota. Passing it through saves the next person an hour.
        log.warning("kb_tts: %s: %s", exc.code, str(detail)[:300])
        raise TTSError("Text to speech failed (%d): %s" % (exc.code, str(detail)[:300]), 502)
    except Exception as exc:                                   # noqa: BLE001
        raise TTSError("Text to speech could not be reached (%s)" % type(exc).__name__, 502)
    audio = data.get("audioContent")
    if not audio:
        raise TTSError("Text to speech returned no audio", 502)
    return base64.b64decode(audio)


def probe():
    """One tiny real synthesis, for the Observability page."""
    if not enabled():
        return {"ok": False, "detail": "switched off"}
    started = time.monotonic()
    try:
        data = synthesize("ok", DEFAULT_ENGINE, DEFAULT_VOICE)
    except TTSError as exc:
        return {"ok": False, "detail": str(exc), "status": exc.status}
    return {"ok": True, "bytes": len(data), "ms": int((time.monotonic() - started) * 1000),
            "engine": DEFAULT_ENGINE, "voice": DEFAULT_VOICE}
