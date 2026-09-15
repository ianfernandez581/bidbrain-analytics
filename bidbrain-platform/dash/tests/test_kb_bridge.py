"""kb_bridge (K7-06): the dashboard staff assistant reading the knowledge base. OFFLINE - the index
is stubbed, Gemini is a fake requests.post, nothing reaches GCS.

Runs under pytest and `python -m unittest` alike.
"""
import os
import sys
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

import kb_index       # noqa: E402
import kb_store       # noqa: E402
import kb_activity    # noqa: E402
import kb_bridge      # noqa: E402
import internal_chat  # noqa: E402

EXCERPTS = [
    {"document_id": "d_plan", "title": "Q3 media plan", "folder": "Media plans", "kind": "plan", "trust": "standard",
     "owner": "charles@100.digital", "ord": 2, "passage": "LinkedIn is held at 18,000 a month until the Q4 review.",
     "found_by": ["keyword", "semantic"]},
    {"document_id": "d_fix", "title": "Correction: rate card", "folder": "Media buyer knowledge", "kind": "feedback",
     "trust": "verified", "owner": "ian@100.digital", "ord": 0, "passage": "The Reddit line is billed at media cost.",
     "found_by": ["semantic"]},
]


def search_ok(q, **kw):
    return {"excerpts": EXCERPTS, "semantic": True, "semantic_error": "", "documents_searched": 12, "outcome": "ok"}


def search_wording_only(q, **kw):
    return {"excerpts": EXCERPTS[:1], "semantic": False, "semantic_error": "Vertex embeddings are switched off",
            "documents_searched": 12, "outcome": "ok"}


class Query(unittest.TestCase):
    def test_last_user_message_is_the_query(self):
        msgs = [{"role": "user", "content": "what did we agree with Cloudflare about the LinkedIn budget?"}]
        self.assertEqual(kb_bridge.shape_query(msgs), msgs[0]["content"])

    def test_short_follow_up_is_prefixed_with_the_previous_question(self):
        msgs = [{"role": "user", "content": "what did we agree about the LinkedIn budget?"},
                {"role": "assistant", "content": "18k a month [1]."},
                {"role": "user", "content": "and for Q3?"}]
        self.assertEqual(kb_bridge.shape_query(msgs), "what did we agree about the LinkedIn budget? and for Q3?")

    def test_a_full_question_is_not_prefixed(self):
        msgs = [{"role": "user", "content": "first question about spend"},
                {"role": "user", "content": "which publishers did the Q3 plan buy for Schneider AET?"}]
        self.assertEqual(kb_bridge.shape_query(msgs), msgs[1]["content"])

    def test_no_user_message_means_no_query(self):
        self.assertEqual(kb_bridge.shape_query([{"role": "assistant", "content": "hi"}]), "")


class Retrieve(unittest.TestCase):
    def test_scoped_to_the_client_and_logged_as_a_dashboard_question(self):
        with mock.patch.object(kb_index, "search", side_effect=search_ok) as s, \
             mock.patch.object(kb_activity, "log_event") as le:
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "LinkedIn budget agreed?"}], actor="ian@100.digital")
        self.assertEqual(s.call_args.kwargs["client"], "cloudflare")
        self.assertEqual(s.call_args.kwargs["limit"], kb_bridge.LIMIT)
        self.assertEqual([p["n"] for p in ret["passages"]], [1, 2])
        self.assertEqual(ret["passages"][1]["trust"], "verified")
        self.assertEqual(le.call_args.args[0], "question")
        self.assertEqual(le.call_args.kwargs["source"], "dashboard")
        self.assertEqual(le.call_args.kwargs["client"], "cloudflare")

    def test_search_failure_degrades_not_raises(self):
        with mock.patch.object(kb_index, "search", side_effect=RuntimeError("bucket down")), \
             mock.patch.object(kb_activity, "log_event"):
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "anything?"}])
        self.assertEqual(ret["passages"], [])
        self.assertIn("unreachable", ret["semantic_error"])

    def test_nothing_to_search_with_is_none(self):
        self.assertIsNone(kb_bridge.retrieve("cloudflare", []))


class Context(unittest.TestCase):
    def test_numbered_passages_and_verified_label(self):
        with mock.patch.object(kb_index, "search", side_effect=search_ok), mock.patch.object(kb_activity, "log_event"):
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "LinkedIn budget?"}])
        ctx = kb_bridge.render_context(ret)
        self.assertIn("=== LIBRARY", ctx)
        self.assertIn("[1] Media plans · Q3 media plan (plan)\nLinkedIn is held", ctx)
        self.assertIn("[2] Media buyer knowledge · Correction: rate card (feedback) - VERIFIED CORRECTION", ctx)
        self.assertNotIn("WORDING ONLY", ctx)

    def test_wording_only_is_stated_in_the_context(self):
        with mock.patch.object(kb_index, "search", side_effect=search_wording_only), mock.patch.object(kb_activity, "log_event"):
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "LinkedIn budget?"}])
        ctx = kb_bridge.render_context(ret)
        self.assertIn("searched by WORDING ONLY - Vertex embeddings are switched off", ctx)

    def test_empty_library_says_so_and_none_renders_nothing(self):
        ret = {"passages": [], "semantic": True, "semantic_error": "", "query": "q", "searched": 0}
        self.assertIn("nothing in the library bears on this question", kb_bridge.render_context(ret))
        self.assertEqual(kb_bridge.render_context(None), "")

    def test_sources_carry_a_capped_snippet_and_the_doc_id(self):
        long = dict(EXCERPTS[0], passage="x" * 900)
        with mock.patch.object(kb_index, "search", return_value={"excerpts": [long], "semantic": True}), \
             mock.patch.object(kb_activity, "log_event"):
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "budget please"}])
        src = kb_bridge.sources_for(ret)
        self.assertEqual(src[0]["doc_id"], "d_plan")
        self.assertEqual(len(src[0]["snippet"]), kb_bridge.SNIPPET_CHARS + 1)     # + the ellipsis


class Chat(unittest.TestCase):
    """internal_chat.chat carries the LIBRARY block and returns sources; without retrieval nothing changes."""

    def _gemini_ok(self):
        r = mock.Mock(status_code=200)
        r.json.return_value = {"candidates": [{"content": {"parts": [{"text": "Held at 18k [1]."}]}}]}
        return r

    def test_library_block_rides_in_system_instruction_and_sources_come_back(self):
        with mock.patch.object(kb_index, "search", side_effect=search_ok), mock.patch.object(kb_activity, "log_event"):
            ret = kb_bridge.retrieve("cloudflare", [{"role": "user", "content": "LinkedIn budget?"}])
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
             mock.patch.object(internal_chat, "_lineage_text", return_value=""), \
             mock.patch.object(internal_chat, "_notes_context", return_value="(none)"), \
             mock.patch.object(internal_chat.requests, "post", return_value=self._gemini_ok()) as post:
            res = internal_chat.chat("cloudflare", [{"role": "user", "content": "LinkedIn budget?"}], "{}",
                                     retrieved=ret, profile="- NFP, outcomes are enquiries")
        body = post.call_args.kwargs["json"]
        sysi = body["systemInstruction"]["parts"][0]["text"]
        self.assertIn("=== LIBRARY", sysi)
        self.assertIn("=== CLIENT PROFILE", sysi)
        self.assertIn("[1] Media plans · Q3 media plan", sysi)
        self.assertEqual([s["n"] for s in res["sources"]], [1, 2])
        self.assertIn("Cite a passage inline as [n]", sysi)

    def test_without_retrieval_the_prompt_has_no_library_block(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}), \
             mock.patch.object(internal_chat, "_lineage_text", return_value=""), \
             mock.patch.object(internal_chat, "_notes_context", return_value="(none)"), \
             mock.patch.object(internal_chat.requests, "post", return_value=self._gemini_ok()) as post:
            res = internal_chat.chat("cloudflare", [{"role": "user", "content": "hi"}], "{}")
        sysi = post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"]
        self.assertNotIn("=== LIBRARY", sysi)
        self.assertNotIn("=== CLIENT PROFILE", sysi)
        self.assertEqual(res["sources"], [])


class Route(unittest.TestCase):
    """The two-gate rule, end to end through /internal-chat/<client>."""

    def setUp(self):
        import main
        self.main = main
        main.app.config["TESTING"] = True
        self.c = main.app.test_client()
        self.patches = [
            mock.patch.object(main, "_internal_allowed", return_value=True),
            mock.patch.object(main, "_upstream_data_json", return_value="{}"),
            mock.patch.object(main.internal_chat, "enabled", return_value=True),
            mock.patch.object(main.internal_chat, "chat", return_value={"answer": "a", "thinking": "", "actions": [],
                                                                        "notes_changed": False, "sources": []}),
            mock.patch.object(kb_index, "search", side_effect=search_ok),
            mock.patch.object(kb_activity, "log_event"),
            mock.patch("kb_memory.profile_block", return_value="- fact"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _as(self, kind, email=None, agency=None):
        with self.c.session_transaction() as s:
            s.clear()
            s["kind"] = kind
            if email:
                s["email"] = email
            if agency:
                s["agency_slug"] = agency

    def _turn(self):
        r = self.c.post("/internal-chat/cloudflare", json={"messages": [{"role": "user", "content": "LinkedIn budget?"}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return self.main.internal_chat.chat.call_args.kwargs

    def test_flag_off_means_no_library_even_for_a_superadmin(self):
        self._as("superadmin", "ian@100.digital")
        with mock.patch.object(self.main, "KNOWLEDGE_RETRIEVAL", False):
            kw = self._turn()
        self.assertIsNone(kw["retrieved"])
        self.assertEqual(kw["profile"], "")

    def test_flag_on_admin_gets_the_library(self):
        self._as("admin", "charles@100.digital")
        with mock.patch.object(self.main, "KNOWLEDGE_RETRIEVAL", True):
            kw = self._turn()
        self.assertEqual([p["n"] for p in kw["retrieved"]["passages"]], [1, 2])
        self.assertEqual(kw["profile"], "- fact")

    def test_flag_on_but_not_kb_allowed_means_no_library(self):
        # an internal agency that may see the dashboard's staff widget but is NOT admitted to /kb
        self._as("agency", agency="transmission")
        with mock.patch.object(self.main, "KNOWLEDGE_RETRIEVAL", True):
            kw = self._turn()
        self.assertIsNone(kw["retrieved"])

    def test_flag_on_100_digital_agency_gets_the_library(self):
        self._as("agency", agency=self.main.KB_AGENCY)
        with mock.patch.object(self.main, "KNOWLEDGE_RETRIEVAL", True):
            kw = self._turn()
        self.assertIsNotNone(kw["retrieved"])


if __name__ == "__main__":
    unittest.main()
