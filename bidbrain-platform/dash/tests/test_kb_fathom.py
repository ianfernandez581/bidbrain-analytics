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


def gemini_reply(client_key, confidence, why="named the client"):
    r = mock.Mock()
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(
        {"client_key": client_key, "confidence": confidence, "why": why})}]}}]}
    return r


# --- the document -----------------------------------------------------------------------------------

class Document(unittest.TestCase):
    def test_body_is_summary_first_then_timestamped_turns(self):
        b = kb_fathom.meeting_body(MEETING)
        self.assertTrue(b.startswith("## Summary\nAgreed to hold LinkedIn"))
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
        r = kb_fathom.classify(m, {}, {}, CANDIDATES, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "", "domain"))

    def test_rung1_declared_domain_assigns_without_a_model(self):
        post = mock.Mock()
        r = kb_fathom.classify(MEETING, {"cloudflare": ["cloudflare.com"]}, {}, CANDIDATES, _post=post, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "domain"))
        post.assert_not_called()

    def test_rung1_two_clients_same_domain_is_a_hint_not_an_assignment(self):
        r = kb_fathom.classify(MEETING, {"cloudflare": ["cloudflare.com"], "mongodb": ["cloudflare.com"]}, {}, CANDIDATES,
                               _post=lambda b: gemini_reply("cloudflare", 0.6), vote=lambda m: ({}, []))
        self.assertEqual(r["decision"], "queue")
        self.assertTrue(any("cloudflare.com" in e for e in r["evidence"]))

    def test_rung2_memory_assigns_on_an_unambiguous_person(self):
        mems = {"cloudflare": {"people": {"priya@cloudflare.com": {"n": 3}}, "titles": {}}}
        r = kb_fathom.classify(MEETING, {}, mems, CANDIDATES, vote=lambda m: ({}, []))
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "cloudflare", "memory"))

    def test_rung2_person_on_two_clients_demotes_to_hint(self):
        mems = {"cloudflare": {"people": {"priya@cloudflare.com": {"n": 3}}, "titles": {}},
                "mongodb": {"people": {"priya@cloudflare.com": {"n": 1}}, "titles": {}}}
        r = kb_fathom.classify(MEETING, {}, mems, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.5), vote=lambda m: ({}, []))
        self.assertEqual(r["decision"], "queue")

    def test_rung3_queues_in_the_pilot_even_at_high_confidence(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            r = kb_fathom.classify(MEETING, {}, {}, CANDIDATES, _post=lambda b: gemini_reply("cloudflare", 0.98),
                                   vote=lambda m: ({"cloudflare": 4}, ["4 of 4 similar passages are from cloudflare meetings"]))
        self.assertEqual(r["decision"], "queue")
        self.assertEqual(r["proposal"]["client_key"], "cloudflare")
        self.assertIn("4 of 4 similar passages are from cloudflare meetings", r["evidence"])

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
        self.assertEqual(out["why"], "classifier unavailable")

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
        with mock.patch.object(kb_index, "search", return_value=res), mock.patch.object(kb_index, "all_meta", return_value=metas):
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
            mock.patch.object(main, "_prod_mutation_blocked", return_value=None),
            mock.patch.object(main, "_fathom_entities", return_value={}),
            mock.patch.object(kb_index, "all_meta", return_value=[]),
            mock.patch.object(kb_index, "search", return_value={"excerpts": []}),
            mock.patch.object(kb_index, "reindex_document", return_value={"chunks": 2, "semantic": True}),
            mock.patch.object(kb_store, "write_file", return_value="meeting.json"),
            mock.patch.object(kb_store, "read_doc", return_value=None),
        ]
        for p in self.patches:
            p.start()
        import kb_fathom_routes
        kb_fathom_routes._clients = main._kb_clients
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
            r = self.c.post("/fathom/webhook", data=body,
                            headers={"webhook-id": "m", "webhook-timestamp": ts, "webhook-signature": "v1," + sig})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["decision"], "queue")        # no domains, no memory, no key -> a person decides
        self._as("admin", "charles@100.digital")
        q = self.c.get("/kb/api/fathom/unassigned").get_json()["items"]
        self.assertEqual([x["recording_id"] for x in q], ["7781"])

    def test_assign_files_and_teaches_then_queue_is_empty(self):
        self._as("admin", "charles@100.digital")
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.fs.write_json("fathom/unassigned/7781/meeting.json", MEETING)
            self.assertEqual(self.c.post("/kb/api/fathom/assign", json={"recording_id": "7781", "client_key": "acme"}).status_code, 404)
            r = self.c.post("/kb/api/fathom/assign", json={"recording_id": "7781", "client_key": "cloudflare"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["doc"]["client"], "cloudflare")
        self.assertEqual(self.c.get("/kb/api/fathom/unassigned").get_json()["items"], [])
        mem = self.c.get("/kb/api/fathom/memory/cloudflare").get_json()["memory"]
        self.assertIn("priya@cloudflare.com", mem["people"])

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
