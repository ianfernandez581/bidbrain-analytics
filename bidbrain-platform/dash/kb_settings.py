"""kb_settings.py - each person's own assistant settings: which model answers, and which voice.

ONE JSON PER ACTOR, at `kb/settings/<actor_key>.json`, beside their conversations.

🔴 SERVER SIDE, NOT `localStorage`. A model choice that lives only in a browser is a different
assistant on a laptop and on a phone, and it is lost the day somebody clears their site data. It
also has to be readable by the SERVER, because the model is chosen before a single token is
streamed. localStorage keeps only what is genuinely per-device: whether the panel is open, and its
size.

🔴 EVERY FIELD HAS A SERVER DEFAULT AND AN UNKNOWN VALUE FALLS BACK TO IT. A saved preference is a
STALE preference the moment a model is retired or a voice is renamed, and a settings file is
exactly the kind of thing nobody migrates. `resolve()` is the one place that decides what a saved
value means today, so a retired model reads as "use the default" rather than as an error on
somebody's next question.
"""
import json
import logging

import kb_chat
import kb_store
import kb_tts

log = logging.getLogger(__name__)

PREFIX = "settings"

# "" means "whatever the deployment's own order says" (kb_chat.available), which is what somebody
# who has never opened settings should get, and what keeps a fallback working.
MODEL_AUTO = ""

DEFAULTS = {
    "model": MODEL_AUTO,
    # Whether an ANSWER is read aloud. The microphone is separate and works either way: dictation
    # is reviewable text, and nothing is ever sent by the microphone or by a pause.
    "speak_replies": False,
    # browser = the free voice built into the browser, which never touches the server.
    "voice_engine": "browser",
    "voice_name": kb_tts.DEFAULT_VOICE,
}


def _path(actor):
    return "%s/%s.json" % (PREFIX, kb_store.actor_key(actor))


def read(actor):
    """The saved settings, merged over the defaults. Never raises: an unreadable settings object
    must not stop somebody asking a question."""
    out = dict(DEFAULTS)
    try:
        doc = kb_store._read_json(_path(actor))         # noqa: SLF001 - same storage layer
    except Exception:                                   # noqa: BLE001
        doc = None
    if isinstance(doc, dict):
        for k in DEFAULTS:
            if k in doc:
                out[k] = doc[k]
    return out


def write(actor, patch):
    """Merge a patch in and save. Returns the resolved settings, so the caller never has to guess
    what was actually stored."""
    cur = read(actor)
    for k, v in (patch or {}).items():
        if k in DEFAULTS:
            cur[k] = v
    cur["model"] = cur["model"] if cur["model"] in kb_chat.PROVIDERS else MODEL_AUTO
    cur["speak_replies"] = bool(cur["speak_replies"])
    if cur["voice_engine"] not in ("browser",) + tuple(kb_tts.ENGINES):
        cur["voice_engine"] = DEFAULTS["voice_engine"]
    if cur["voice_name"] not in kb_tts.VOICES:
        cur["voice_name"] = kb_tts.DEFAULT_VOICE
    try:
        kb_store._write_json(_path(actor), cur)         # noqa: SLF001
    except Exception:                                   # noqa: BLE001
        log.warning("kb_settings: could not save settings for this actor", exc_info=True)
    return cur


def resolve(actor):
    """Settings plus what they MEAN for this deployment right now.

    `model_effective` is the provider that will actually answer: a chosen model that is not
    configured here falls back rather than failing, and `model_note` says so on the settings
    screen instead of letting somebody wonder why their choice is being ignored.
    """
    s = read(actor)
    avail = kb_chat.available()
    chosen = s["model"] if s["model"] in kb_chat.PROVIDERS else MODEL_AUTO
    note = ""
    if chosen and chosen not in avail:
        note = ("%s has no API key on this deployment, so %s is answering instead."
                % (kb_chat.LABELS.get(chosen, chosen),
                   kb_chat.LABELS.get(avail[0], avail[0]) if avail else "no model"))
        effective = avail[0] if avail else ""
    else:
        effective = chosen or (avail[0] if avail else "")
    return {
        **s,
        "model_effective": effective,
        "model_note": note,
        "models": [{"id": p, "label": kb_chat.LABELS[p], "model": kb_chat.model_of(p),
                    "configured": kb_chat.configured(p)} for p in kb_chat.PROVIDERS],
        "tts": kb_tts.catalog(),
    }
