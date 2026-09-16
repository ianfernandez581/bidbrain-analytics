"""kb_fathom + kb_memory + kb_fathom_routes (K7-03). OFFLINE: the store is a dict, the index is a
stub, Gemini is a fake `_post`. Nothing here reaches GCS, Vertex, Gemini or Fathom.

Runs under pytest (Ian's runner) and under `python -m unittest` alike.
"""
import os
import sys
import json
import hmac
import time
import base64
import hashlib
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("PLATFORM_BACKEND", "memory")
os.environ.setdefault("SESSION_SECRET", "t")
os.environ.setdefault("SSO_SECRET", "t")
os.environ.setdefault("COOKIE_DOMAIN", "")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bidbrain-analytics")

import kb_store      # noqa: E402
import kb_index      # noqa: E402
import kb_memory     # noqa: E402
import kb_fathom     # noqa: E402


# --- an in-memory stand-in for the bucket --------------------------------------------------------

class FakeStore:
    """kb_store._read_json/_write_json + list_blobs over a dict, keyed by full object name."""
    def __init__(self):
        self.objects = {}

    def read_json(self, path, default=None):
        return json.loads(self.objects[f"{kb_store.PREFIX}/{path}"]) if f"{kb_store.PREFIX}/{path}" in self.objects else default

    def write_json(self, path, obj, if_generation=None):
        self.objects[f"{kb_store.PREFIX}/{path}"] = json.dumps(obj)
        return 1

    def list_blobs(self, bucket, prefix=""):
        out = []
        for name in sorted(self.objects):
            if name.startswith(prefix):
                out.append(_Blob(name, self))
        return out


class _Blob:
    def __init__(self, name, store):
        self.name, self._s = name, store

    def download_as_bytes(self):
        return self._s.objects[self.name].encode("utf-8")

    def delete(self):
        self._s.objects.pop(self.name, None)


def patch_store(fs):
    return [mock.patch.object(kb_store, "_read_json", fs.read_json),
            mock.patch.object(kb_store, "_write_json", fs.write_json),
            mock.patch.object(kb_store, "_storage", lambda: mock.Mock(list_blobs=fs.list_blobs))]


MEETING = {
    "recording_id": 7781, "title": "Cloudflare weekly - 12 Sep", "created_at": "2026-09-12T03:00:00Z",
    "recording_start_time": "2026-09-12T03:00:00Z", "recording_end_time": "2026-09-12T03:31:00Z",
    "url": "https://fathom.video/calls/7781", "recorded_by": {"email": "charles@100.digital"},
    "default_summary": "Agreed to hold LinkedIn at 18k until the Q4 review.",
    "calendar_invitees": [{"email": "charles@100.digital", "email_domain": "100.digital", "is_external": False},
                          {"email": "priya@cloudflare.com", "email_domain": "cloudflare.com", "is_external": True}],
    "transcript": [{"speaker": {"display_name": "Priya"}, "text": "CTR dropped on APAC Core DG last week.", "timestamp": "00:00:04"},
                   {"speaker": {"display_name": "Charles"}, "text": "We hold spend at 18k and review Reddit next month.", "timestamp": "00:00:19"}],
}
CANDIDATES = [{"key": "cloudflare", "name": "Cloudflare"}, {"key": "mongodb", "name": "MongoDB"}]


REAL_SHAPE = dict(MEETING, recording_id=7782, title="Daily Dev Standup",
                  recorded_by={"email": "christian@bidbrain.ai", "email_domain": "bidbrain.ai"},
                  # the LIVE API: summary is an object, and the 100.digital colleague is "external" to a
                  # bidbrain.ai recorder (2026-09-16, first real sync)
                  default_summary={"template_name": "general", "markdown_formatted": "## Notes\nShipped the Meetings page."},
                  calendar_invitees=[{"email": "christian@bidbrain.ai", "email_domain": "bidbrain.ai", "is_external": False},
                                     {"email": "charles@100.digital", "email_domain": "100.digital", "is_external": True}])


class RealFathomShape(unittest.TestCase):
    def test_summary_links_are_stripped_and_one_link_kept(self):
        m = dict(REAL_SHAPE, share_url="https://fathom.video/share/abc",
                 default_summary={"template_name": "Enhanced", "markdown_formatted":
                                  "## Key Takeaways\n\n  - [**Reports first:** replicate the UI.](https://fathom.video/share/abc?t=394)"})
        body = kb_fathom.meeting_body(m)
        self.assertIn("- **Reports first:** replicate the UI.", body)
        self.assertNotIn("?t=394", body)                       # the per-line link is gone
        self.assertEqual(body.count("https://fathom.video/share/abc"), 1)   # ... one link stays, at the top

    def test_transcript_merges_consecutive_lines_of_one_speaker(self):
        m = dict(REAL_SHAPE, transcript=[
            {"speaker": {"display_name": "Charles"}, "text": "Yan.", "timestamp": "00:00:07"},
            {"speaker": {"display_name": "Charles"}, "text": "Yan, yan.", "timestamp": "00:00:08"},
            {"speaker": {"display_name": "Juan"}, "text": "Depende.", "timestamp": "00:00:24"},
            {"speaker": {"display_name": "Charles"}, "text": "Sige.", "timestamp": "00:00:30"}])
        lines, cut = kb_fathom.transcript_turns(m)
        self.assertEqual(lines, ["[00:00:07] Charles: Yan. Yan, yan.", "[00:00:24] Juan: Depende.", "[00:00:30] Charles: Sige."])
        self.assertFalse(cut)

    def test_object_summary_is_read_not_stringified(self):
        body = kb_fathom.meeting_body(REAL_SHAPE)
        self.assertIn("Shipped the Meetings page.", body)
        self.assertNotIn("markdown_formatted", body)           # no dict repr in the document
        self.assertNotIn("{", kb_fathom.summary_text(REAL_SHAPE))
        # the evidence rung and the vote read the same text without raising
        self.assertEqual(kb_fathom.entity_match(REAL_SHAPE, {"cloudflare": {"Core DG APAC"}}), {})

    def test_agency_domain_is_internal_whatever_fathom_says(self):
        self.assertFalse(kb_memory.is_external({"email": "charles@100.digital", "email_domain": "100.digital", "is_external": True}))
        self.assertTrue(kb_memory.is_external({"email": "priya@cloudflare.com", "email_domain": "cloudflare.com", "is_external": True}))
        # rung 0: a stand-up of bidbrain.ai + 100.digital people is INTERNAL -> a SURE agency-wide guess, no model
        r = kb_fathom.classify(REAL_SHAPE, {}, {}, CANDIDATES, _post=lambda b: self.fail("model must not be called"))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "", "internal"))
        # and a colleague is never offered as something to remember about a client
        self.assertEqual(kb_memory.teaches(REAL_SHAPE)["people"], [])
        self.assertEqual(kb_fathom.external_domains(REAL_SHAPE), [])


def gemini_reply(client_key, confidence, why="named the client"):
    r = mock.Mock()
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(
        {"client_key": client_key, "confidence": confidence, "why": why})}]}}]}
    return r


# --- the document -----------------------------------------------------------------------------------

class Document(unittest.TestCase):
    def test_body_is_summary_first_then_timestamped_turns(self):
        b = kb_fathom.meeting_body(MEETING)
        self.assertTrue(b.startswith("## Summary\nOpen in Fathom: https://fathom.video/calls/7781\n\nAgreed to hold LinkedIn"), b[:120])
        self.assertIn("## Transcript\n[00:00:04] Priya: CTR dropped", b)
        self.assertLess(b.index("## Summary"), b.index("## Transcript"))

    def test_body_declares_a_cut(self):
        b = kb_fathom.meeting_body(MEETING, max_transcript_chars=30)
        self.assertIn("[Import note: this transcript was cut to fit", b)

    def test_doc_id_is_stable_and_store_safe(self):
        self.assertEqual(kb_fathom.doc_id(MEETING), "fathom-7781")
        kb_store._safe_id(kb_fathom.doc_id({"recording_id": "a/b c"}))    # sanitised, does not raise

    def test_title_carries_the_date(self):
        self.assertEqual(kb_fathom.meeting_title(MEETING), "Cloudflare weekly - 12 Sep (2026-09-12)")

    def test_index_meeting_files_under_client_keeps_raw_and_learns(self):
        fs = FakeStore()
        written = {}
        with mock.patch.multiple(kb_store, _read_json=fs.read_json, _write_json=fs.write_json,
                                 _storage=lambda: mock.Mock(list_blobs=fs.list_blobs),
                                 write_file=lambda did, fn, data, content_type="": written.setdefault(did, fn)), \
             mock.patch.object(kb_index, "reindex_document", return_value={"chunks": 3, "semantic": True}) as rx:
            meta = kb_fathom.index_meeting(MEETING, "cloudflare", "human", evidence=['campaign "APAC Core DG" found in cloudflare\'s dashboard data'])
        doc = rx.call_args.args[0]
        self.assertEqual((doc["kind"], doc["source"], doc["folder"], doc["client"]), ("meeting", "fathom", "Meetings", "cloudflare"))
        self.assertEqual(doc["fathom"]["recording_id"], "7781")
        self.assertEqual(written, {"fathom-7781": "meeting.json"})
        self.assertEqual(meta["chunks"], 3)
        mem = kb_memory.load("cloudflare") if False else json.loads(fs.objects[f"{kb_store.PREFIX}/fathom/memory/cloudflare.json"])
        self.assertIn("priya@cloudflare.com", mem["people"])
        self.assertNotIn("charles@100.digital", mem["people"])          # internal invitee never learned
        self.assertIn("cloudflare weekly", mem["titles"])
        self.assertIn("APAC Core DG", mem["patterns"])

    def test_model_assignment_does_not_teach(self):
        fs = FakeStore()
        with mock.patch.multiple(kb_store, _read_json=fs.read_json, _write_json=fs.write_json,
                                 _storage=lambda: mock.Mock(list_blobs=fs.list_blobs), write_file=lambda *a, **k: "f"), \
             mock.patch.object(kb_index, "reindex_document", return_value={"chunks": 1, "semantic": False}):
            kb_fathom.index_meeting(MEETING, "cloudflare", "model")
        self.assertFalse(any(k.endswith("memory/cloudflare.json") for k in fs.objects))


# --- the queue --------------------------------------------------------------------------------------

class Queue(unittest.TestCase):
    def test_store_list_load_drop(self):
        fs = FakeStore()
        with mock.patch.multiple(kb_store, _read_json=fs.read_json, _write_json=fs.write_json,
                                 _storage=lambda: mock.Mock(list_blobs=fs.list_blobs)):
            kb_fathom.store_unassigned(MEETING, proposal={"client_key": "cloudflare", "confidence": 0.7, "evidence": ["x"]})
            items = kb_fathom.list_unassigned()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["recording_id"], "7781")
            self.assertEqual(items[0]["proposal"]["client_key"], "cloudflare")
            self.assertEqual(items[0]["duration_min"], 31)
            self.assertEqual(kb_fathom.load_unassigned("7781")["title"], MEETING["title"])
            kb_fathom.drop_unassigned("7781")
            self.assertEqual(kb_fathom.list_unassigned(), [])


# --- the ladder -------------------------------------------------------------------------------------

class Ladder(unittest.TestCase):
    def test_rung0_internal_only_is_agency_wide(self):
        m = dict(MEETING, calendar_invitees=[{"email": "a@100.digital", "is_external": False}])
        # DEFAULT (Jerome, 2026-09-16: "95-100% auto assign"): a sure rung is 100% -> it files itself
        r = kb_fathom.classify(m, {}, {}, CANDIDATES, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "", "internal"))
        # ... and with self-filing switched off it becomes a 100% guess a person confirms
        r = kb_fathom.classify(m, {}, {}, CANDIDATES, vote=lambda m: ({}, []), auto_file=frozenset())
        self.assertEqual((r["decision"], r["confidence"], r["proposal"]["client_key"], r["proposal"]["sure_by"]), ("queue", 1.0, "", "internal"))

    def test_watch_list_titles_always_wait_even_when_filing_is_on(self):
        m = dict(MEETING, title="Interview - senior media buyer", calendar_invitees=[{"email": "a@100.digital", "is_external": False}])
        r = kb_fathom.classify(m, {}, {}, CANDIDATES, vote=lambda m: ({}, []), auto_file={"internal", "domain", "memory"})
        self.assertEqual(r["decision"], "queue")
        self.assertIn("watch-list ('interview')", r["proposal"]["why"])
        self.assertEqual(kb_fathom.watched_title({"title": "Cloudflare weekly"}), "")
        self.assertEqual(kb_fathom.watched_title({"title": "Charles / Priya 1:1"}), "1:1")
        self.assertEqual(kb_fathom.watched_title({"title": "HR policy walkthrough"}), "hr")
        self.assertEqual(kb_fathom.watched_title({"title": "Chrome update"}), "")          # 'hr' inside a word is not a hit

    def test_rung1_declared_domain_assigns_without_a_model(self):
        post = mock.Mock()
        r = kb_fathom.classify(MEETING, {"cloudflare": ["cloudflare.com"]}, {}, CANDIDATES, _post=post, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "domain"))
        post.assert_not_called()
        r = kb_fathom.classify(MEETING, {"cloudflare": ["cloudflare.com"]}, {}, CANDIDATES, _post=post, vote=lambda m: ({}, []), auto_file=frozenset())
        self.assertEqual((r["decision"], r["proposal"]["client_key"], r["proposal"]["confidence"], r["proposal"]["sure_by"]), ("queue", "cloudflare", 1.0, "domain"))

    def test_rung1_two_clients_same_domain_is_a_hint_not_an_assignment(self):
        r = kb_fathom.classify(MEETING, {"cloudflare": ["cloudflare.com"], "mongodb": ["cloudflare.com"]}, {}, CANDIDATES,
                               _post=lambda b: gemini_reply("cloudflare", 0.6), vote=lambda m: ({}, []))
        self.assertEqual(r["decision"], "queue")
        self.assertTrue(any("cloudflare.com" in e for e in r["evidence"]))

    def test_rung2_memory_assigns_on_an_unambiguous_person(self):
        mems = {"cloudflare": {"people": {"priya@cloudflare.com": {"n": 3}}, "titles": {}}}
        r = kb_fathom.classify(MEETING, {}, mems, CANDIDATES, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "memory"))
        r = kb_fathom.classify(MEETING, {}, mems, CANDIDATES, vote=lambda m: ({}, []), auto_file=frozenset())
        self.assertEqual((r["decision"], r["proposal"]["client_key"], r["proposal"]["sure_by"]), ("queue", "cloudflare", "memory"))

    def test_rung2_person_on_two_clients_demotes_to_hint(self):
        mems = {"cloudflare": {"people": {"priya@cloudflare.com": {"n": 3}}, "titles": {}},
                "mongodb": {"people": {"priya@cloudflare.com": {"n": 1}}, "titles": {}}}
        r = kb_fathom.classify(MEETING, {}, mems, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.5), vote=lambda m: ({}, []))
        self.assertEqual(r["decision"], "queue")

    def test_rung3_files_at_95_and_waits_below_it(self):
        """Jerome, 2026-09-16: 95-100% files itself; when the system is not sure, a person decides."""
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.98),
                                   vote=lambda m: ({"cloudflare": 4}, ["4 of 4 similar passages are from cloudflare meetings"]))
            self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "model"))
            self.assertIn("4 of 4 similar passages are from cloudflare meetings", r["evidence"])
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.95), vote=lambda m: ({}, []))
            self.assertEqual(r["decision"], "assign")                                      # 95 is in
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.94), vote=lambda m: ({}, []))
            self.assertEqual((r["decision"], r["proposal"]["client_key"]), ("queue", "cloudflare"))   # 94 waits
            # a model filing NEVER teaches memory (index_meeting learns only from domain/memory/human/internal)
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.98),
                                   vote=lambda m: ({}, []), auto_assign=1.01)
            self.assertEqual(r["decision"], "queue")                                       # and 1.01 still means never

    def test_rung3_assigns_when_the_threshold_is_lowered(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, auto_assign=0.9, _post=lambda b: gemini_reply("cloudflare", 0.95),
                                   vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "model"))

    def test_synthesise_rejects_a_key_outside_the_list(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            out = kb_fathom.synthesise(MEETING, CANDIDATES, [], _post=lambda b: gemini_reply("acme", 0.99))
        self.assertEqual((out["client_key"], out["confidence"]), ("", 0.0))

    def test_synthesise_without_a_key_is_unavailable_not_a_call(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            out = kb_fathom.synthesise(MEETING, CANDIDATES, [], _post=mock.Mock(side_effect=AssertionError("called")))
        self.assertEqual(out["why"], "classifier unavailable: no GEMINI_API_KEY in this process")

    def test_entity_match_ignores_short_and_shared_names(self):
        ents = {"cloudflare": {"APAC Core DG", "Q3"}, "mongodb": {"APAC Core DG", "Atlas Growth Wave"}}
        hits = kb_fathom.entity_match(MEETING, ents)
        self.assertEqual(hits, {})                                      # shared name discriminates nothing
        hits = kb_fathom.entity_match(MEETING, {"cloudflare": {"APAC Core DG"}})
        self.assertIn("cloudflare", hits)

    def test_corpus_vote_counts_only_filed_fathom_meetings(self):
        res = {"excerpts": [{"document_id": "fathom-1"}, {"document_id": "fathom-2"}, {"document_id": "d_plan"}]}
        metas = [{"id": "fathom-1", "kind": "meeting", "source": "fathom", "client": "cloudflare"},
                 {"id": "fathom-2", "kind": "meeting", "source": "fathom", "client": "cloudflare"},
                 {"id": "d_plan", "kind": "plan", "source": "upload", "client": "mongodb"}]
        with mock.patch.object(kb_index, "search", return_value=res), mock.patch.object(kb_index, "all_meta", return_value={m["id"]: m for m in metas}):
            tally, ev = kb_fathom.corpus_vote(MEETING)
        self.assertEqual(tally, {"cloudflare": 2})
        self.assertEqual(ev, ["2 of 2 similar passages are from cloudflare meetings"])


# --- webhook signature --------------------------------------------------------------------------------

class Signature(unittest.TestCase):
    def _sign(self, secret_b64, wid, ts, body):
        sec = base64.b64decode(secret_b64)
        return base64.b64encode(hmac.new(sec, f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()

    def test_whsec_secret_verifies_and_tolerance_applies(self):
        raw = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
        secret = "whsec_" + raw
        body = b'{"recording_id": 1}'
        now = int(time.time())
        sig = self._sign(raw, "msg_1", str(now), body)
        h = {"webhook-id": "msg_1", "webhook-timestamp": str(now), "webhook-signature": "v1," + sig}
        self.assertTrue(kb_fathom.verify_signature(h, body, secret, now=now))
        self.assertFalse(kb_fathom.verify_signature(h, body + b" ", secret, now=now))
        self.assertFalse(kb_fathom.verify_signature(h, body, secret, now=now + 400))
        self.assertFalse(kb_fathom.verify_signature(h, body, "", now=now))


# --- memory -------------------------------------------------------------------------------------------

class Memory(unittest.TestCase):
    def test_norm_title(self):
        self.assertEqual(kb_memory.norm_title("Cloudflare weekly - 12 Sep"), "cloudflare weekly")
        self.assertEqual(kb_memory.norm_title("MongoDB / Bidbrain sync 2026-09-12 (Fri)"), "mongodb bidbrain sync")

    def test_declared_domains_validated_and_read_by_the_ladder(self):
        fs = FakeStore()
        with mock.patch.multiple(kb_store, _read_json=fs.read_json, _write_json=fs.write_json,
                                 _storage=lambda: mock.Mock(list_blobs=fs.list_blobs)):
            saved, bad = kb_memory.set_client_domains("cloudflare", ["Cloudflare.com", "@cloudflare.net"])
            self.assertEqual((saved, bad), (["cloudflare.com", "cloudflare.net"], []))
            saved, bad = kb_memory.set_client_domains("cloudflare", ["not a domain"])
            self.assertEqual(bad, ["not a domain"])
            self.assertEqual(kb_memory.all_client_domains(), {"cloudflare": ["cloudflare.com", "cloudflare.net"]})

    def test_client_safe_is_facts_only(self):
        mem = dict(kb_memory.empty(), facts=["NFP"], people={"p@x.com": {"n": 1}})
        self.assertEqual(kb_memory.client_safe(mem), {"facts": ["NFP"]})


# --- routes -------------------------------------------------------------------------------------------

class Routes(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        main.app.config["TESTING"] = True
        self.c = main.app.test_client()
        self.fs = FakeStore()
        self.patches = patch_store(self.fs) + [
            mock.patch.object(main, "_kb_clients", return_value=[{"key": "cloudflare", "name": "Cloudflare"}]),
            mock.patch.object(main, "_kb_registry_clients", return_value=[{"key": "cloudflare", "name": "Cloudflare"},
                                                                          {"key": "mongodb", "name": "MongoDB"}]),
            mock.patch.object(main, "_prod_mutation_blocked", return_value=None),
            mock.patch.object(main, "_fathom_entities", return_value={}),
            mock.patch.object(kb_index, "all_meta", return_value={}),
            mock.patch.object(kb_index, "search", return_value={"excerpts": []}),
            mock.patch.object(kb_index, "reindex_document", return_value={"chunks": 2, "semantic": True}),
            mock.patch.object(kb_store, "write_file", return_value="meeting.json"),
            mock.patch.object(kb_store, "read_doc", return_value=None),
        ]
        for p in self.patches:
            p.start()
        import kb_fathom_routes
        kb_fathom_routes._clients = main._kb_clients
        kb_fathom_routes._registry_clients = main._kb_registry_clients
        kb_fathom_routes._blocked = main._prod_mutation_blocked
        kb_fathom_routes._entities = main._fathom_entities

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _as(self, kind, email=None):
        with self.c.session_transaction() as s:
            s.clear()
            s["kind"] = kind
            if email:
                s["email"] = email

    def test_page_and_api_follow_the_kb_gate(self):
        self.assertEqual(self.c.get("/kb/meetings").status_code, 302)         # signed out -> login
        self.assertEqual(self.c.get("/kb/api/fathom/status").status_code, 401)
        self._as("client")
        self.assertEqual(self.c.get("/kb/meetings").status_code, 403)
        self._as("admin", "charles@100.digital")
        r = self.c.get("/kb/meetings")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Waiting for a client", r.get_data(as_text=True))

    def test_sync_without_a_key_is_503(self):
        self._as("admin", "charles@100.digital")
        with mock.patch.dict(os.environ, {"FATHOM_API_KEY": ""}):
            r = self.c.post("/kb/api/fathom/sync", json={})
        self.assertEqual(r.status_code, 503)

    def test_webhook_unconfigured_then_bad_signature_then_queued(self):
        with mock.patch.dict(os.environ, {"FATHOM_WEBHOOK_SECRET": ""}):
            self.assertEqual(self.c.post("/fathom/webhook", data=b"{}").status_code, 503)
        raw = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
        with mock.patch.dict(os.environ, {"FATHOM_WEBHOOK_SECRET": "whsec_" + raw, "GEMINI_API_KEY": ""}):
            body = json.dumps(MEETING).encode()
            self.assertEqual(self.c.post("/fathom/webhook", data=body,
                                         headers={"webhook-id": "m", "webhook-timestamp": str(int(time.time())),
                                                  "webhook-signature": "v1,bad"}).status_code, 401)
            ts = str(int(time.time()))
            sig = base64.b64encode(hmac.new(base64.b64decode(raw), f"m.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
            import threading
            r = self.c.post("/fathom/webhook", data=body,
                            headers={"webhook-id": "m", "webhook-timestamp": ts, "webhook-signature": "v1," + sig})
            # 2026-09-15: the webhook answers FIRST (Fathom retries a slow endpoint) and the meeting
            # is already in the queue when it does; the ladder runs in a background thread.
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json()["decision"], "accepted")
            self.assertIn(f"{kb_store.PREFIX}/fathom/unassigned/7781/meeting.json", self.fs.objects)
            for t in threading.enumerate():
                if t.name == "fathom-ladder":
                    t.join(timeout=10)
        # no declared domain, no memory, no key -> the ladder QUEUED it with a proposal; a person decides
        self.assertIn(f"{kb_store.PREFIX}/fathom/unassigned/7781/proposal.json", self.fs.objects)
        self._as("admin", "charles@100.digital")
        q = self.c.get("/kb/api/fathom/unassigned").get_json()["items"]
        self.assertEqual([x["recording_id"] for x in q], ["7781"])
        self.assertIn("no GEMINI_API_KEY", q[0]["proposal"]["why"])       # candidates were present; the KEY was the gap

    def test_ladder_candidates_come_from_the_registry_not_the_session(self):
        """A webhook has no session and the ladder runs in a thread with no request context: the
        candidate list must never touch flask.session (2026-09-15, found by the level-2 re-run)."""
        import kb_fathom_routes as FR
        with mock.patch.object(FR, "_clients", side_effect=RuntimeError("Working outside of request context")):
            self.assertEqual([c["key"] for c in FR._candidates()], ["cloudflare", "mongodb"])

    def test_webhook_replies_before_the_ladder_runs(self):
        """The slow half must never sit in front of the reply: accept() returns with process() not yet
        called, and a re-delivered meeting that is already filed is 'exists' without queueing."""
        import kb_fathom_routes as FR
        started = []
        with mock.patch.object(FR, "process", side_effect=lambda m: started.append(kb_fathom.recording_id(m))), \
             mock.patch.object(FR.threading, "Thread") as thr:
            res = FR.accept(MEETING)
        self.assertEqual(res["decision"], "accepted")
        self.assertEqual(started, [])                                   # not run inline
        self.assertEqual(thr.call_args.kwargs["name"], "fathom-ladder")
        self.assertIn(f"{kb_store.PREFIX}/fathom/unassigned/7781/meeting.json", self.fs.objects)
        with mock.patch.object(kb_store, "read_doc", return_value={"id": "fathom-7781", "client": "cloudflare"}):
            self.assertEqual(FR.accept(MEETING), {"decision": "exists", "client_key": "cloudflare"})

    def test_assign_files_and_teaches_then_queue_is_empty(self):
        self._as("admin", "charles@100.digital")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.fs.write_json("fathom/unassigned/7781/meeting.json", MEETING)
            self.assertEqual(self.c.post("/kb/api/fathom/assign", json={"recording_id": "7781", "client_key": "acme"}).status_code, 404)
            r = self.c.post("/kb/api/fathom/assign", json={"recording_id": "7781", "client_key": "cloudflare"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["doc"]["client"], "cloudflare")
        self.assertEqual(self.c.get("/kb/api/fathom/unassigned").get_json()["items"], [])
        # the "N filed" counter reads all_meta's VALUES ({doc_id: meta}); iterating the dict itself gave 0
        with mock.patch.object(kb_index, "all_meta", return_value={"fathom-7781": {"id": "fathom-7781", "kind": "meeting", "source": "fathom"},
                                                                    "d2": {"id": "d2", "kind": "reference", "source": "upload"}}):
            self.assertEqual(self.c.get("/kb/api/fathom/status").get_json()["indexed"], 1)
        mem = self.c.get("/kb/api/fathom/memory/cloudflare").get_json()["memory"]
        self.assertIn("priya@cloudflare.com", mem["people"])

    def test_sync_retries_a_queued_meeting_that_never_got_a_proposal(self):
        """Seven real meetings sat in the queue with no guess after a classifier crash; the watermark
        meant no later sync would revisit them (2026-09-16). Sync now re-runs the ladder on them."""
        import kb_fathom_routes as FR
        self._as("admin", "charles@100.digital")
        internal = dict(REAL_SHAPE, recording_id=7790)          # all-agency stand-up: rung 0 files it
        self.fs.write_json("fathom/unassigned/7790/meeting.json", internal)
        self.fs.write_json("fathom/unassigned/7790/proposal.json", {"evidence": ["classifier error"]})
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), \
             mock.patch.object(kb_fathom, "fetch_meetings", return_value=[]):
            FR._sync_quietly("key", "2026-09-01T00:00:00Z", "tester")
        # the retried stand-up is SURE (internal) -> it files itself and leaves the queue
        self.assertEqual(self.c.get("/kb/api/fathom/unassigned").get_json()["items"], [])
        st = kb_fathom.state()
        self.assertEqual((st["last_counts"]["retried"], st["last_counts"]["assigned"]), (1, 1))

    def test_queue_says_what_assign_will_teach_and_unticked_items_are_not_learned(self):
        """The card shows 'Will remember: ...' with tick boxes (2026-09-15 polish). Unticking sends
        the item in `skip`; the meeting is still filed, the item is simply not recorded."""
        self._as("admin", "charles@100.digital")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.fs.write_json("fathom/unassigned/7781/meeting.json", MEETING)
            item = self.c.get("/kb/api/fathom/unassigned").get_json()["items"][0]
            self.assertEqual(item["will_learn"]["people"], ["priya@cloudflare.com"])
            self.assertEqual(item["will_learn"]["domains"], ["cloudflare.com"])
            self.assertEqual(item["will_learn"]["title"], "cloudflare weekly")
            r = self.c.post("/kb/api/fathom/assign", json={"recording_id": "7781", "client_key": "cloudflare",
                                                           "skip": ["priya@cloudflare.com", "cloudflare weekly"]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        mem = self.c.get("/kb/api/fathom/memory/cloudflare").get_json()["memory"]
        self.assertNotIn("priya@cloudflare.com", mem["people"])        # unticked
        self.assertNotIn("cloudflare weekly", mem["titles"])           # unticked
        self.assertIn("cloudflare.com", mem["domains"])                # still ticked -> learned

    def test_memory_edits(self):
        self._as("admin", "charles@100.digital")
        r = self.c.post("/kb/api/fathom/memory/cloudflare", json={"domains": ["cloudflare.com", "bad domain"]})
        self.assertEqual(r.status_code, 400)
        r = self.c.post("/kb/api/fathom/memory/cloudflare", json={"domains": ["cloudflare.com"]})
        self.assertEqual(r.get_json()["memory"]["client_domains"], ["cloudflare.com"])
        r = self.c.post("/kb/api/fathom/memory/cloudflare", json={"fact": "NFP - outcomes are enquiries"})
        self.assertEqual(r.get_json()["memory"]["facts"], ["NFP - outcomes are enquiries"])
        r = self.c.post("/kb/api/fathom/memory/cloudflare", json={"forget": {"kind": "facts", "key": "NFP - outcomes are enquiries"}})
        self.assertTrue(r.get_json()["removed"])
        self.assertEqual(self.c.post("/kb/api/fathom/memory/acme", json={"fact": "x"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
