"""K5-02 / K5-05 / K5-06: the Customer Assistant module, its route (billed-basis data, client
audience, fail-closed), and the injected widget. Gemini, GCS and the upstream fetch are mocked."""
import os
import sys
import json
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import client_chat as CC  # noqa: E402

try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False

os.environ.setdefault("SESSION_SECRET", "x")
os.environ.setdefault("SSO_SECRET", "x")
os.environ.setdefault("DEV", "1")
os.environ.setdefault("ALLOW_PROD_MUTATIONS", "1")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bidbrain-analytics")
os.environ["GEMINI_API_KEY"] = "k"
if HAVE_FLASK:
    import main  # noqa: E402


def _gemini(text):
    r = mock.Mock()
    r.status_code = 200
    r.json.return_value = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return r


RET = {"passages": [{"n": 1, "doc_id": "d_plan", "title": "Q3 plan", "folder": "", "kind": "plan",
                     "trust": "standard", "owner": "", "ord": 0, "text": "LinkedIn target USD 18k/month.",
                     "found_by": ["keyword"]}],
       "semantic": True, "semantic_error": "", "query": "plan?", "searched": 3, "audience": "client"}


class Module(unittest.TestCase):
    def test_system_prompt_is_client_safe(self):
        self.assertIsNone(CC.FORBIDDEN_IN_CONTEXT.search(CC.SYSTEM))
        self.assertIn(CC.DISCLAIMER, CC.SYSTEM)
        self.assertIn("Never invent a figure", CC.SYSTEM)
        for word in ("raw media cost", "INTERNAL", "provenance", "BigQuery", "lineage", "data.json"):
            self.assertNotIn(word, CC.SYSTEM, word)

    def test_context_refuses_forbidden_tokens(self):
        for bad in ('{"spend_multipliers":{"ttd":2}}', "window.BB_SPEND_MULT", "our margin is", "_rawSpend"):
            with self.assertRaises(ValueError, msg=bad):
                CC.build_context("cloudflare", bad, "", None)
        ctx = CC.build_context("cloudflare", '{"kpi":{"spend":10}}', "CPM = cost per thousand", RET)
        self.assertIn("billed basis", ctx)
        self.assertIn("=== GLOSSARY ===\nCPM", ctx)
        self.assertIn("=== RETRIEVED CONTEXT (documents shared with you", ctx)   # client-audience header, no folders/owners
        self.assertIn("[1] Q3 plan\nLinkedIn target USD 18k/month.", ctx)

    def test_chat_has_no_tools_no_thinking_and_returns_sources(self):
        with mock.patch.object(CC.requests, "post", return_value=_gemini("Hold at 18k [1].")) as post:
            res = CC.chat("cloudflare", [{"role": "user", "content": "budget?"}], "{}", "", retrieved=RET)
        body = post.call_args.kwargs["json"]
        self.assertNotIn("tools", body)
        self.assertNotIn("thinkingConfig", body["generationConfig"])
        self.assertEqual([c["role"] for c in body["contents"]], ["user"])
        self.assertEqual(res["answer"], "Hold at 18k [1].")
        self.assertEqual(res["sources"][0]["n"], 1)
        self.assertEqual(post.call_args.args[0], CC.ENDPOINT.format(model=CC.MODEL))

    def test_model_override(self):
        with mock.patch.object(CC.requests, "post", return_value=_gemini("ok")) as post:
            CC.chat("c", [{"role": "user", "content": "q"}], "{}", model="gemini-2.5-pro")
        self.assertIn("gemini-2.5-pro", post.call_args.args[0])


@unittest.skipUnless(HAVE_FLASK, "flask not importable")
class Route(unittest.TestCase):
    RAW = {"kpi": {"spend_aud": 100.0, "clicks": 5}, "rows": [{"spend": 10.0, "imps": 100}],
           "owner": "Ian F", "contacts": [{"email": "priya@cloudflare.com", "name": "Priya"}]}

    def setUp(self):
        main.app.config["TESTING"] = True
        self.c = main.app.test_client()
        self.flag = {"cloudflare": True, "mongodb": False}
        self.patches = [
            mock.patch.object(main.store, "get_client_chat", side_effect=lambda k: self.flag.get(k, False)),
            mock.patch.object(main.store, "get_client", side_effect=lambda k: {"url": "https://x"} if k in self.flag else None),
            mock.patch.object(main.store, "get_spend_multipliers", return_value={}),
            mock.patch.object(main, "_upstream_data_json", return_value=json.dumps(self.RAW)),
            mock.patch.object(main, "_log_customer_turn"),
            # the master switch is OFF by default (Jerome, 2026-09-15) - these tests exercise the plumbing
            mock.patch.object(main, "CLIENT_CHAT_ENABLED", True),
            mock.patch.object(main.client_chat, "chat", return_value={"answer": "a", "sources": []}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _as_client(self, key):
        with self.c.session_transaction() as s:
            s.clear()
            s["kind"] = "client"
            s["client_key"] = key

    def test_flag_off_or_wrong_dashboard_is_403(self):
        self._as_client("mongodb")
        self.assertEqual(self.c.post("/client-chat/mongodb", json={"messages": [{"role": "user", "content": "q"}]}).status_code, 403)
        self.assertEqual(self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "q"}]}).status_code, 403)

    def test_customer_data_is_billed_basis_and_scrubbed(self):
        self._as_client("cloudflare")
        r = self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "how much spend?"}]})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        data_txt = main.client_chat.chat.call_args.args[2]
        doc = json.loads(data_txt)
        # cloudflare has no billed-spend spec => every money field SUPPRESSED, never raw
        self.assertIsNone(doc["kpi"]["spend_aud"])
        self.assertIsNone(doc["rows"][0]["spend"])
        self.assertEqual(doc["kpi"]["clicks"], 5)                 # non-money intact
        self.assertNotIn("owner", doc)                            # named individuals scrubbed
        self.assertNotIn("priya@cloudflare.com", data_txt)
        self.assertIsNone(CC.FORBIDDEN_IN_CONTEXT.search(data_txt))
        # retrieval ran through kb_bridge.retrieve_for_client; with no client-visible documents it
        # is an EMPTY block, never None (the mock below is what makes this test's index non-empty)

    def test_retrieval_uses_the_client_audience_read(self):
        import kb_bridge
        self._as_client("cloudflare")
        with mock.patch.object(kb_bridge, "retrieve_for_client", return_value=RET) as ret:
            r = self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "plan?"}]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ret.call_args.args[0], "cloudflare")
        self.assertEqual(main.client_chat.chat.call_args.kwargs["retrieved"], RET)

    def test_master_switch_off_hides_everything_even_with_the_flag_on(self):
        self._as_client("cloudflare")
        with mock.patch.object(main, "CLIENT_CHAT_ENABLED", False):
            self.assertFalse(main._client_chat_allowed("cloudflare"))
            r = self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "q"}]})
        self.assertEqual(r.status_code, 403)

    def test_fails_closed_when_billed_data_cannot_be_prepared(self):
        self._as_client("cloudflare")
        with mock.patch.object(main, "_upstream_data_json", side_effect=RuntimeError("upstream down")):
            r = self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "q"}]})
        self.assertEqual(r.status_code, 503)
        main.client_chat.chat.assert_not_called()

    def test_forbidden_token_in_context_is_refused_not_sent(self):
        self._as_client("cloudflare")
        main.client_chat.chat.side_effect = ValueError("forbidden token")
        r = self.c.post("/client-chat/cloudflare", json={"messages": [{"role": "user", "content": "q"}]})
        self.assertEqual(r.status_code, 502)

    def test_widget_is_namespaced_and_carries_no_internal_badge(self):
        w = main._client_widget("cloudflare").decode()
        self.assertIn("var CLIENT='cloudflare'", w)
        self.assertIn("/client-chat/", w)
        self.assertNotIn("INTERNAL", w)
        self.assertNotIn("bbin-", w)
        self.assertNotIn("/internal-", w)


if __name__ == "__main__":
    unittest.main()
