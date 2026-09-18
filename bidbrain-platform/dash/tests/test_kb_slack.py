"""kb_slack + kb_slack_routes. OFFLINE: the store is a dict, the index is a stub, Slack is a fake
`_get`, Gemini is a fake `_post`. Nothing here reaches GCS, Vertex, Gemini or Slack.

Runs under pytest (Ian's runner) and under `python -m unittest` alike.
"""
import os
import sys
import json
import hmac
import time
import hashlib
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)                       # the fathom rig lives beside this file
os.environ.setdefault("PLATFORM_BACKEND", "memory")
os.environ.setdefault("SESSION_SECRET", "t")
os.environ.setdefault("SSO_SECRET", "t")
os.environ.setdefault("COOKIE_DOMAIN", "")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bidbrain-analytics")
os.environ["SLACK_TZ"] = "UTC"               # fixtures below are written in UTC

import kb_store      # noqa: E402
import kb_index      # noqa: E402
import kb_slack      # noqa: E402
from test_kb_fathom import FakeStore, patch_store, gemini_reply   # noqa: E402  - the same rig


# --- fixtures ---------------------------------------------------------------------------------------

CH = {"id": "C0GEO", "name": "geocon", "is_private": False}
USERS = {"U1": {"name": "Charles", "email": "charles@100.digital", "is_bot": False},
         "U2": {"name": "Jerome", "email": "jerome@bidbrain.ai", "is_bot": False},
         "U9": {"name": "Sam (Geocon)", "email": "sam@geocon.com.au", "is_bot": False}}

# 2026-09-17 09:00 UTC = 1789635600
T0 = 1789635600.0
def ts(offset_s):
    return "%.6f" % (T0 + offset_s)

PARENT = {"type": "message", "user": "U9", "ts": ts(0), "text": "Can we pause the <https://ads.google.com|Search campaign> until Monday?",
          "reply_count": 2, "latest_reply": ts(900),
          "_replies": [{"type": "message", "user": "U1", "ts": ts(600), "thread_ts": ts(0), "text": "Yes <@U2> can you action?"},
                       {"type": "message", "user": "U2", "ts": ts(900), "thread_ts": ts(0), "text": "Done &amp; confirmed. See <#C0GEO|geocon>"}]}
LOOSE1 = {"type": "message", "user": "U1", "ts": ts(3600), "text": "Weekly report attached", "files": [{"name": "geocon-w37.pdf", "title": "Geocon W37"}]}
LOOSE2 = {"type": "message", "user": "U2", "ts": ts(7200), "text": "<!here> dashboards refreshed"}
JOIN = {"type": "message", "subtype": "channel_join", "user": "U2", "ts": ts(10), "text": "<@U2> has joined the channel"}
NEXT_DAY = {"type": "message", "user": "U9", "ts": ts(86400 + 60), "text": "Thanks all"}
MSGS = [PARENT, JOIN, LOOSE1, LOOSE2, NEXT_DAY]


def sign(secret, body, t=None):
    t = str(int(t or time.time()))
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{t}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": t, "X-Slack-Signature": sig}


class FakeSlack:
    """A tiny Web API: routes method -> responder(params) -> dict. Counts calls, can 429 once."""
    def __init__(self, routes, limit_once=None):
        self.routes, self.calls, self.limit_once = routes, [], limit_once

    def __call__(self, url, params):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, dict(params)))
        r = mock.Mock()
        if self.limit_once == method:
            self.limit_once = None
            r.status_code, r.headers, r.text = 429, {"Retry-After": "1"}, "ratelimited"
            return r
        r.status_code, r.headers = 200, {}
        fn = self.routes.get(method)
        r.json.return_value = fn(params) if fn else {"ok": False, "error": f"unknown_method:{method}"}
        return r


# --- signing ----------------------------------------------------------------------------------------

class Signing(unittest.TestCase):
    def test_good_signature_passes_and_tampering_fails(self):
        body = b'{"type":"event_callback"}'
        h = sign("s3cret", body)
        self.assertTrue(kb_slack.verify_signature(h, body, "s3cret"))
        self.assertFalse(kb_slack.verify_signature(h, body + b" ", "s3cret"))
        self.assertFalse(kb_slack.verify_signature(h, body, "other"))
        self.assertFalse(kb_slack.verify_signature(h, body, ""))

    def test_stale_timestamp_is_rejected(self):
        body = b"{}"
        h = sign("s", body, t=time.time() - 3600)
        self.assertFalse(kb_slack.verify_signature(h, body, "s"))
        h2 = sign("s", body)
        self.assertTrue(kb_slack.verify_signature(h2, body, "s", now=time.time() + 100))
        self.assertFalse(kb_slack.verify_signature(h2, body, "s", now=time.time() + 1000))

    def test_missing_headers_fail_closed(self):
        self.assertFalse(kb_slack.verify_signature({}, b"{}", "s"))
        self.assertFalse(kb_slack.verify_signature({"X-Slack-Signature": "v0=abc"}, b"{}", "s"))


# --- text -------------------------------------------------------------------------------------------

class Text(unittest.TestCase):
    def test_mentions_channels_links_and_entities_read_as_prose(self):
        t = kb_slack.render_text("Yes <@U2> can you action? See <#C0GEO|geocon> &amp; <https://x.y|the plan> or <https://z.w>",
                                 USERS, {"C0GEO": {"name": "geocon"}})
        self.assertEqual(t, "Yes @Jerome can you action? See #geocon & the plan (https://x.y) or https://z.w")
        self.assertEqual(kb_slack.render_text("<!here> go <!subteam^S1|@ads-team>"), "@here go @ads-team")
        self.assertEqual(kb_slack.render_text("<@U404>", USERS), "@U404")        # unknown id stays an id, never raises

    def test_message_line_has_time_speaker_text_and_file_names_only(self):
        self.assertEqual(kb_slack.message_line(LOOSE1, USERS), "[10:00] Charles: Weekly report attached [file: Geocon W37]")
        bot = {"ts": ts(0), "text": "", "username": "Looker", "attachments": [{"fallback": "Spend is up 12%"}]}
        self.assertEqual(kb_slack.message_line(bot, USERS), "[09:00] Looker: Spend is up 12%")


# --- conversations ----------------------------------------------------------------------------------

class Conversations(unittest.TestCase):
    def test_threads_stand_alone_and_loose_messages_group_by_day(self):
        convs = kb_slack.group_conversations(MSGS, CH)
        kinds = [(c["kind"], c["key"], len(c["messages"])) for c in convs]
        self.assertEqual(kinds, [("thread", "t" + ts(0).replace(".", "-"), 3),
                                 ("day", "d2026-09-17", 2),            # the join is furniture and is gone
                                 ("day", "d2026-09-18", 1)])
        self.assertEqual(convs[0]["thread_ts"], ts(0))

    def test_titles_and_ids(self):
        convs = kb_slack.group_conversations(MSGS, CH)
        self.assertEqual(kb_slack.conversation_title(convs[0], USERS),
                         "Can we pause the Search campaign (https://ads.google.com) until Monday? (#geocon, 2026-09-17)")
        self.assertEqual(kb_slack.conversation_title(convs[1], USERS), "#geocon - 2026-09-17")
        did = kb_slack.doc_id(CH["id"], convs[0]["key"])
        self.assertEqual(did, "slack-C0GEO-t1789635600-000000")
        kb_store._safe_id(did)                                          # store-safe, does not raise
        self.assertEqual(kb_slack.doc_id("C0GEO", "d2026-09-17"), "slack-C0GEO-d2026-09-17")

    def test_body_reads_as_a_transcript_with_a_permalink(self):
        conv = kb_slack.group_conversations(MSGS, CH)[0]
        b = kb_slack.conversation_body(conv, USERS, {"C0GEO": {"name": "geocon"}}, team_url="https://100digital.slack.com/")
        self.assertTrue(b.startswith("## #geocon - 2026-09-17 (thread)\nOpen in Slack: https://100digital.slack.com/archives/C0GEO/p1789635600000000\n3 message(s)"), b[:160])
        self.assertIn("[09:10] Charles: Yes @Jerome can you action?", b)
        self.assertIn("[09:15] Jerome: Done & confirmed. See #geocon", b)
        self.assertNotIn("<@", b)
        self.assertNotIn("&amp;", b)

    def test_body_declares_a_cut(self):
        big = {"id": "C1", "name": "big", "is_private": False}
        msgs = [{"type": "message", "user": "U1", "ts": ts(i), "text": "x" * 4000} for i in range(120)]
        conv = kb_slack.group_conversations(msgs, big)[0]
        b = kb_slack.conversation_body(conv, USERS)
        self.assertIn("[Import note: this conversation was cut to fit", b)
        self.assertLess(len(b), kb_store.MAX_BODY_CHARS)

    def test_meeting_view_lets_the_fathom_ladder_read_it(self):
        conv = kb_slack.group_conversations(MSGS, CH)[0]
        m = kb_slack.as_meeting(conv, USERS)
        # the people who SPOKE stand in for invitees, so memory can learn a recurring guest (S6-02)
        self.assertEqual([i["email"] for i in m["calendar_invitees"]], ["sam@geocon.com.au", "charles@100.digital", "jerome@bidbrain.ai"])
        import kb_memory
        self.assertEqual(kb_memory.teaches(m)["people"], ["sam@geocon.com.au"])    # colleagues are internal by domain
        self.assertEqual(m["transcript"][1], {"speaker": {"display_name": "Charles"}, "text": "Yes @Jerome can you action?", "timestamp": "09:10:00"})
        import kb_fathom
        self.assertIn("[09:10:00] Charles: Yes @Jerome", kb_fathom.meeting_body(m))
        # the evidence rung reads it too
        self.assertEqual(list(kb_fathom.entity_match(m, {"geocon": {"Search campaign"}})), ["geocon"])


# --- the Web API --------------------------------------------------------------------------------------

class WebApi(unittest.TestCase):
    def test_history_pages_attaches_replies_and_reports_is_limited(self):
        pages = {None: {"ok": True, "messages": [PARENT_NO_REPLIES := dict(PARENT, _replies=None), LOOSE1], "is_limited": True,
                        "response_metadata": {"next_cursor": "c2"}},
                 "c2": {"ok": True, "messages": [LOOSE2], "response_metadata": {"next_cursor": ""}}}
        pages[None]["messages"][0].pop("_replies")
        fake = FakeSlack({"conversations.history": lambda p: pages[p.get("cursor")],
                          "conversations.replies": lambda p: {"ok": True, "messages": [dict(PARENT, _replies=None)] + PARENT["_replies"]}})
        msgs, limited = kb_slack.fetch_history("C0GEO", oldest="1", tok="xoxb-t", _get=fake)
        self.assertTrue(limited)
        self.assertEqual([m["ts"] for m in msgs], [ts(0), ts(3600), ts(7200)])
        self.assertEqual([r["ts"] for r in msgs[0]["_replies"]], [ts(600), ts(900)])   # the parent is not its own reply
        methods = [m for m, _ in fake.calls]
        self.assertEqual(methods, ["conversations.history", "conversations.history", "conversations.replies"])
        self.assertEqual(fake.calls[0][1]["oldest"], "1")

    def test_a_429_waits_and_retries_and_not_ok_raises(self):
        fake = FakeSlack({"auth.test": lambda p: {"ok": True, "team": "100% Digital", "team_id": "T1", "user_id": "UB", "url": "https://x.slack.com/"}},
                         limit_once="auth.test")
        waits = []
        with mock.patch.object(kb_slack, "MAX_RETRY_WAIT_S", 60):
            j = kb_slack.call("auth.test", tok="t", _get=fake, _sleep=waits.append)
        self.assertEqual(j["team"], "100% Digital")
        self.assertEqual(waits, [1])
        bad = FakeSlack({"auth.test": lambda p: {"ok": False, "error": "invalid_auth"}})
        with self.assertRaises(kb_slack.SlackError) as cm:
            kb_slack.call("auth.test", tok="t", _get=bad)
        self.assertIn("invalid_auth", str(cm.exception))

    def test_only_member_channels_exist(self):
        fake = FakeSlack({"conversations.list": lambda p: {"ok": True, "channels": [
            {"id": "C0GEO", "name": "geocon", "is_member": True, "is_private": False, "num_members": 4},
            {"id": "C0GEN", "name": "general", "is_member": False, "is_private": False, "num_members": 40}]}})
        chans = kb_slack.list_channels(tok="t", _get=fake)
        self.assertEqual([c["id"] for c in chans], ["C0GEO"])

    def test_public_only_app_falls_back_when_private_scope_is_missing(self):
        def lst(p):
            if "private" in p.get("types", ""):
                return {"ok": False, "error": "missing_scope"}
            return {"ok": True, "channels": [{"id": "C0GEO", "name": "geocon", "is_member": True}]}
        fake = FakeSlack({"conversations.list": lst})
        self.assertEqual([c["name"] for c in kb_slack.list_channels(tok="t", _get=fake)], ["geocon"])
        self.assertEqual(fake.calls[-1][1]["types"], "public_channel")


# --- filing -------------------------------------------------------------------------------------------

class Filing(unittest.TestCase):
    def setUp(self):
        self.fs = FakeStore()
        self.written = {}
        self.patches = patch_store(self.fs) + [
            mock.patch.object(kb_store, "write_file", lambda did, fn, data, content_type="": self.written.setdefault(did, fn)),
            mock.patch.object(kb_index, "reindex_document", return_value={"chunks": 2, "semantic": True}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_index_conversation_files_under_client_in_a_channel_folder(self):
        conv = kb_slack.group_conversations(MSGS, CH)[0]
        meta = kb_slack.index_conversation(conv, "geocon", "channel", evidence=["channel #geocon is mapped to geocon"],
                                           users_by_id=USERS, team_url="https://x.slack.com")
        doc = kb_index.reindex_document.call_args.args[0]
        self.assertEqual((doc["kind"], doc["source"], doc["folder"], doc["client"]), ("conversation", "slack", "Slack/#geocon", "geocon"))
        self.assertEqual(doc["slack"]["assigned_by"], "channel")
        self.assertEqual(doc["slack"]["permalink"], "https://x.slack.com/archives/C0GEO/p1789635600000000")
        self.assertEqual(self.written, {"slack-C0GEO-t1789635600-000000": "conversation.json"})
        self.assertEqual(meta["chunks"], 2)

    def test_channel_mapping_is_declared_by_a_person_and_can_be_cleared(self):
        self.assertIsNone(kb_slack.channel_client("C0GEO"))
        kb_slack.set_channel_client("C0GEO", "geocon", name="geocon", by="jerome@bidbrain.ai")
        self.assertEqual(kb_slack.channel_client("C0GEO"), "geocon")
        kb_slack.set_channel_client("C0GEN", "", name="general", by="jerome@bidbrain.ai")   # agency-wide is a real answer
        self.assertEqual(kb_slack.channel_client("C0GEN"), "")
        kb_slack.set_channel_client("C0GEO", None)
        self.assertIsNone(kb_slack.channel_client("C0GEO"))

    def test_queue_round_trip_drops_the_messages_from_the_card(self):
        conv = kb_slack.group_conversations(MSGS, CH)[1]
        kb_slack.store_unassigned(conv, proposal={"client_key": "geocon", "confidence": 0.6, "why": "guess"}, users_by_id=USERS)
        items = kb_slack.list_unassigned()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "#geocon - 2026-09-17")
        self.assertNotIn("conversation", items[0])
        self.assertEqual(items[0]["preview"][0], "[10:00] Charles: Weekly report attached [file: Geocon W37]")
        full = kb_slack.load_unassigned(items[0]["key"])
        self.assertEqual(len(full["conversation"]["messages"]), 2)
        kb_slack.drop_unassigned(items[0]["key"])
        self.assertEqual(kb_slack.list_unassigned(), [])

    def test_purge_removes_every_slack_object(self):
        conv = kb_slack.group_conversations(MSGS, CH)[0]
        kb_slack.index_conversation(conv, "geocon", "channel", users_by_id=USERS)
        kb_slack.store_unassigned(kb_slack.group_conversations(MSGS, CH)[1], users_by_id=USERS)
        kb_slack.set_channel_client("C0GEO", "geocon")
        kb_slack.save_state({"sync_in_progress": False})
        did = "slack-C0GEO-t1789635600-000000"
        deleted = []
        with mock.patch.object(kb_index, "all_meta", return_value={did: {"id": did, "source": "slack"}, "fathom-1": {"source": "fathom"}}), \
             mock.patch.object(kb_store, "delete_doc", deleted.append):
            counts = kb_slack.purge_all()
        self.assertEqual(deleted, [did])
        self.assertEqual(counts["docs"], 1)
        self.assertFalse([k for k in self.fs.objects if "/slack/" in k], "no slack/ object may survive a purge")


if __name__ == "__main__":
    unittest.main()


class Chunking(unittest.TestCase):
    """S4-05: a passage is a set of WHOLE messages. kb_chunk cuts only a block larger than its
    budget, so each message must be its own block (a blank line between them)."""

    def test_no_message_is_ever_cut_mid_line(self):
        import kb_chunk
        big = {"id": "C1", "name": "busy", "is_private": False}
        # 60 messages of ~30 words: ~1,800 words, so 8+ chunks
        msgs = [{"type": "message", "user": ["U1", "U2", "U9"][i % 3], "ts": ts(i * 60),
                 "text": f"Message {i}: " + " ".join(f"word{i}_{k}" for k in range(28))} for i in range(60)]
        conv = kb_slack.group_conversations(msgs, big)[0]
        body = kb_slack.conversation_body(conv, USERS)
        chunks = kb_chunk.chunk_text(body)
        self.assertGreater(len(chunks), 5)
        lines = [ln for ln in body.split("\n") if ln.startswith("[")]
        self.assertEqual(len(lines), 60)
        joined = "\n".join(chunks)
        for ln in lines:
            self.assertIn(ln, joined, f"a message line was cut across passages: {ln[:40]}")
        # A passage may START with the previous passage's 40-word overlap tail (kb_chunk's design);
        # what must never happen is a message existing only in pieces, which the loop above asserts.

    def test_private_channel_is_listed_but_not_readable_by_default(self):
        self.assertTrue(kb_slack.readable({"id": "C1", "is_private": False}))
        with mock.patch.object(kb_slack, "ALLOW_PRIVATE", False):
            self.assertFalse(kb_slack.readable({"id": "C2", "is_private": True}))
        with mock.patch.object(kb_slack, "ALLOW_PRIVATE", True):
            self.assertTrue(kb_slack.readable({"id": "C2", "is_private": True}))
