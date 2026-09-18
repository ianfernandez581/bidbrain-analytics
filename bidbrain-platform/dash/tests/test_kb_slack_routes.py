"""kb_slack_routes through the Flask test client. OFFLINE: FakeStore for the bucket, a stub index,
a FakeSlack for the Web API, Gemini never called (channels are mapped or the ladder is patched).
"""
import os
import sys
import json
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ.setdefault("PLATFORM_BACKEND", "memory")
os.environ.setdefault("SESSION_SECRET", "t")
os.environ.setdefault("SSO_SECRET", "t")
os.environ.setdefault("COOKIE_DOMAIN", "")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bidbrain-analytics")
os.environ["SLACK_TZ"] = "UTC"

import kb_store      # noqa: E402
import kb_index      # noqa: E402
import kb_slack      # noqa: E402
from test_kb_fathom import FakeStore, patch_store          # noqa: E402
from test_kb_slack import CH, USERS, MSGS, PARENT, LOOSE1, LOOSE2, ts, sign, FakeSlack   # noqa: E402

CLIENTS = [{"key": "geocon", "name": "Geocon"}, {"key": "cloudflare", "name": "Cloudflare"}]
OBS_PATH = "/kb/obs/data"


def slack_api(channels=None, history=None):
    """A workspace with one member channel (#geocon) and the fixture history."""
    chans = channels if channels is not None else [{"id": "C0GEO", "name": "geocon", "is_member": True, "is_private": False, "num_members": 4}]
    hist = history if history is not None else [dict(PARENT, _replies=None), LOOSE1, LOOSE2]
    for m in hist:
        m.pop("_replies", None)
    return FakeSlack({
        "auth.test": lambda p: {"ok": True, "team": "100% Digital", "team_id": "T1", "user_id": "UB", "url": "https://x.slack.com/"},
        "users.list": lambda p: {"ok": True, "members": [{"id": k, "profile": {"display_name": v["name"], "email": v["email"]}} for k, v in USERS.items()]},
        "conversations.list": lambda p: {"ok": True, "channels": chans},
        "conversations.history": lambda p: {"ok": True, "messages": hist, "is_limited": False},
        "conversations.replies": lambda p: {"ok": True, "messages": [dict(PARENT)] + PARENT["_replies"]},
    })


class Rig(unittest.TestCase):
    def setUp(self):
        import main
        self.main = main
        main.app.config["TESTING"] = True
        self.c = main.app.test_client()
        self.fs = FakeStore()
        self.events, self.written, self.docs = [], {}, {}
        import kb_activity

        def reindex(doc, **kw):
            self.docs[doc["id"]] = doc
            return {"chunks": 2, "semantic": True, "skipped": False}

        self.patches = patch_store(self.fs) + [
            mock.patch.object(main, "_kb_clients", return_value=CLIENTS),
            mock.patch.object(main, "_kb_registry_clients", return_value=CLIENTS),
            mock.patch.object(main, "_prod_mutation_blocked", return_value=None),
            mock.patch.object(main, "_fathom_entities", return_value={}),
            mock.patch.object(kb_index, "all_meta", side_effect=lambda include_archived=True: {k: {"id": k, "source": d["source"], "client": d["client"]} for k, d in self.docs.items()}),
            mock.patch.object(kb_index, "search", return_value={"excerpts": []}),
            mock.patch.object(kb_index, "reindex_document", side_effect=reindex),
            mock.patch.object(kb_store, "write_file", lambda did, fn, data, content_type="": self.written.setdefault(did, fn)),
            mock.patch.object(kb_store, "read_doc", side_effect=lambda did, with_generation=False: self.docs.get(did)),
            mock.patch.object(kb_activity, "log_event", side_effect=lambda kind, **kw: self.events.append(dict(kind=kind, **kw)) or "id"),
            mock.patch.object(kb_activity, "log", side_effect=lambda kind, **kw: self.events.append(dict(kind=kind, **kw)) or "id"),
            mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_SIGNING_SECRET": "sekrit"}),
            mock.patch.object(kb_slack, "_USERS", {"at": 0.0, "by_id": {}}),
        ]
        for p in self.patches:
            p.start()
        import kb_slack_routes
        self.r = kb_slack_routes
        kb_slack_routes._clients = main._kb_clients
        kb_slack_routes._registry_clients = main._kb_registry_clients
        kb_slack_routes._blocked = main._prod_mutation_blocked
        kb_slack_routes._entities = main._fathom_entities
        kb_slack_routes._SEEN_EVENTS.clear()
        # background threads run inline so a test can assert on their result
        self.thread = mock.patch.object(kb_slack_routes.threading, "Thread",
                                        side_effect=lambda target, args=(), kwargs=None, **k: mock.Mock(start=lambda: target(*args, **(kwargs or {}))))
        self.thread.start()

    def tearDown(self):
        self.thread.stop()
        for p in self.patches:
            p.stop()

    def _as(self, kind, email="charles@100.digital"):
        with self.c.session_transaction() as s:
            s.clear()
            s["kind"] = kind
            s["email"] = email

    def _of(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def _slack(self, fake):
        return mock.patch.object(kb_slack.requests, "get", side_effect=lambda url, params=None, headers=None, timeout=None: fake(url, params or {}))


class Gate(Rig):
    def test_anonymous_and_client_sessions_are_refused(self):
        r = self.c.get("/kb/api/slack/status")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["reason"], "auth")
        self.assertEqual(self.c.get("/kb/channels").status_code, 302)

    def test_the_page_renders_for_staff(self):
        self._as("admin")
        r = self.c.get("/kb/channels")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Channels the bot is in", body)
        self.assertIn("/static/kb_fm.css", body)
        self.assertIn('href="/kb/meetings"', body)
        # and the other pages now link here
        self.assertIn('href="/kb/channels"', self.c.get("/kb/meetings").get_data(as_text=True))


class Sync(Rig):
    def test_a_mapped_channel_files_every_conversation_without_a_model(self):
        self._as("admin")
        kb_slack.set_channel_client("C0GEO", "geocon", name="geocon", by="jerome@bidbrain.ai")
        with self._slack(slack_api()), mock.patch.object(self.r.kb_fathom, "classify") as cls:
            r = self.c.post("/kb/api/slack/sync", json={"since_days": 30})
        self.assertTrue(r.get_json()["ok"], r.get_json())
        cls.assert_not_called()
        st = kb_slack.state()
        self.assertFalse(st["sync_in_progress"])
        self.assertEqual(st["last_counts"]["filed"], 2, st["last_counts"])     # the thread + the day
        self.assertEqual(st["last_error"], "")
        self.assertEqual(st["team"]["team"], "100% Digital")
        self.assertEqual(st["channels"]["C0GEO"]["name"], "geocon")
        docs = sorted(self.docs)
        self.assertEqual(docs, ["slack-C0GEO-d2026-09-17", "slack-C0GEO-t1789635600-000000"])
        d = self.docs["slack-C0GEO-t1789635600-000000"]
        self.assertEqual((d["client"], d["folder"], d["kind"], d["source"]), ("geocon", "Slack/#geocon", "conversation", "slack"))
        self.assertIn("[09:10] Charles: Yes @Jerome can you action?", d["body"])
        self.assertIn("https://x.slack.com/archives/C0GEO/p1789635600000000", d["body"])
        filed = self._of("slack_filed")
        self.assertEqual(len(filed), 2)
        self.assertEqual((filed[0]["client"], filed[0]["by"], filed[0]["channel"]), ("geocon", "channel", "geocon"))

    def test_a_second_sync_rebuilds_in_place_and_logs_nothing_new(self):
        self._as("admin")
        kb_slack.set_channel_client("C0GEO", "geocon")
        with self._slack(slack_api()):
            self.c.post("/kb/api/slack/sync", json={})
            n = len(self.events)
            self.c.post("/kb/api/slack/sync", json={})
        self.assertEqual(len(self.events), n, "a rebuild is not a decision")
        self.assertEqual(kb_slack.state()["last_counts"]["rebuilt"], 2)
        self.assertEqual(len(self.docs), 2)

    def test_a_deleted_message_leaves_the_document_on_the_next_sync(self):
        self._as("admin")
        kb_slack.set_channel_client("C0GEO", "geocon")
        with self._slack(slack_api()):
            self.c.post("/kb/api/slack/sync", json={})
        self.assertIn("dashboards refreshed", self.docs["slack-C0GEO-d2026-09-17"]["body"])
        with self._slack(slack_api(history=[dict(PARENT), dict(LOOSE1)])):          # LOOSE2 deleted in Slack
            self.c.post("/kb/api/slack/sync", json={})
        self.assertNotIn("dashboards refreshed", self.docs["slack-C0GEO-d2026-09-17"]["body"])
        self.assertEqual(self.docs["slack-C0GEO-d2026-09-17"]["client"], "geocon")   # same client, same id

    def test_an_unmapped_channel_goes_through_the_ladder_and_waits(self):
        self._as("admin")
        with self._slack(slack_api()), \
             mock.patch.object(self.r.kb_fathom, "classify", return_value={
                 "decision": "queue", "client_key": None, "assigned_by": None, "confidence": 0.62,
                 "evidence": ["1 of 1 similar passages are from geocon meetings"],
                 "proposal": {"client_key": "geocon", "confidence": 0.62, "why": "mentions Gateway", "evidence": []}}) as cls:
            r = self.c.post("/kb/api/slack/sync", json={})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(cls.call_count, 2)
        m = cls.call_args_list[0].args[0]
        self.assertEqual([i["email"] for i in m["calendar_invitees"]][:1], ["sam@geocon.com.au"])   # authors stand in for invitees
        self.assertTrue(m["title"].startswith("#geocon "))
        self.assertEqual(self.docs, {})
        q = kb_slack.list_unassigned()
        self.assertEqual(len(q), 2)
        self.assertEqual(q[0]["proposal"]["client_key"], "geocon")
        self.assertEqual(len(self._of("slack_queued")), 2)
        self.assertEqual(self._of("slack_queued")[0]["guess"], "geocon")

    def test_a_running_sync_refuses_a_second_and_a_stale_flag_does_not(self):
        self._as("admin")
        kb_slack.save_state({"sync_in_progress": True, "sync_started_ts": time.time() - 5})
        self.assertEqual(self.c.post("/kb/api/slack/sync", json={}).status_code, 409)
        kb_slack.save_state({"sync_in_progress": True, "sync_started_ts": time.time() - 9999})
        j = self.c.get("/kb/api/slack/status?live=0").get_json()
        self.assertFalse(j["state"]["sync_in_progress"])


class CronSync(Rig):
    """The nightly catch-up door. No session - the shared secret IS the auth."""

    HDR = {"X-Bidbrain-Cron": "cronsekrit"}

    def _env(self, **kw):
        base = {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_SIGNING_SECRET": "sekrit",
                "SLACK_CRON_SECRET": "cronsekrit"}
        base.update(kw)
        return mock.patch.dict(os.environ, base)

    def test_no_secret_configured_is_off_not_open(self):
        with mock.patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-test"}, clear=False):
            os.environ.pop("SLACK_CRON_SECRET", None)
            r = self.c.post("/slack/cron/sync", headers=self.HDR, json={})
        self.assertEqual(r.status_code, 503)

    def test_a_wrong_secret_is_refused(self):
        with self._env():
            r = self.c.post("/slack/cron/sync", headers={"X-Bidbrain-Cron": "nope"}, json={})
        self.assertEqual(r.status_code, 401)

    def test_a_missing_header_is_refused(self):
        with self._env():
            r = self.c.post("/slack/cron/sync", json={})
        self.assertEqual(r.status_code, 401)

    def test_the_right_secret_runs_the_same_sweep_with_no_session(self):
        kb_slack.set_channel_client("C0GEO", "geocon")
        with self._env(), self._slack(slack_api()):
            r = self.c.post("/slack/cron/sync", headers=self.HDR, json={})
        self.assertEqual(r.status_code, 202)
        body = r.get_json()
        self.assertTrue(body["ok"] and body["started"])
        self.assertEqual(body["since_days"], 7)              # the default
        st = kb_slack.state()
        self.assertEqual(st["by"], "scheduler")
        self.assertEqual(st["last_counts"]["filed"], 2)
        self.assertEqual(sorted(self.docs), ["slack-C0GEO-d2026-09-17", "slack-C0GEO-t1789635600-000000"])

    def test_since_days_is_honoured_and_clamped(self):
        with self._env(), self._slack(slack_api()):
            r = self.c.post("/slack/cron/sync", headers=self.HDR, json={"since_days": 99999})
        self.assertEqual(r.get_json()["since_days"], 3650)

    def test_the_env_default_can_be_changed_without_a_deploy(self):
        with self._env(SLACK_CRON_DAYS="2"), self._slack(slack_api()):
            r = self.c.post("/slack/cron/sync", headers=self.HDR, json={})
        self.assertEqual(r.get_json()["since_days"], 2)

    def test_it_steps_aside_for_a_sync_already_running(self):
        st = kb_slack.state()
        st.update(sync_in_progress=True, sync_started_ts=time.time())
        kb_slack.save_state(st)
        with self._env(), self._slack(slack_api()) as api:
            r = self.c.post("/slack/cron/sync", headers=self.HDR, json={})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["started"])
        self.assertEqual(self.docs, {})                      # nothing was read

    def test_a_second_run_over_unchanged_history_files_nothing_new(self):
        kb_slack.set_channel_client("C0GEO", "geocon")
        with self._env(), self._slack(slack_api()):
            self.c.post("/slack/cron/sync", headers=self.HDR, json={})
            n = len(self.events)
            self.c.post("/slack/cron/sync", headers=self.HDR, json={})
        self.assertEqual(len(self.events), n, "a nightly re-run must not log a second filing")


class Queue(Rig):
    def _queue_one(self):
        conv = kb_slack.group_conversations([dict(PARENT), LOOSE1], CH)[1]      # the day doc
        kb_slack.store_unassigned(conv, proposal={"client_key": "cloudflare", "confidence": 0.7, "why": "guess"}, users_by_id=USERS)
        return "slack-C0GEO-d2026-09-17"

    def test_assign_files_and_records_whether_the_person_agreed(self):
        self._as("admin", "jerome@bidbrain.ai")
        key = self._queue_one()
        r = self.c.post("/kb/api/slack/assign", json={"key": key, "client_key": "geocon"})
        self.assertTrue(r.get_json()["ok"], r.get_json())
        self.assertEqual(self.docs[key]["client"], "geocon")
        self.assertEqual(self.docs[key]["slack"]["assigned_by"], "human")
        [e] = self._of("slack_assigned")
        self.assertEqual((e["client"], e["guess"], e["agreed"], e["actor"]), ("geocon", "cloudflare", False, "jerome@bidbrain.ai"))
        self.assertEqual(kb_slack.list_unassigned(), [])

    def test_ignore_records_then_drops(self):
        self._as("admin")
        key = self._queue_one()
        r = self.c.post("/kb/api/slack/assign", json={"key": key, "client_key": "ignore"})
        self.assertTrue(r.get_json()["ignored"])
        [e] = self._of("slack_ignored")
        self.assertEqual(e["guess"], "cloudflare")
        self.assertEqual(e["title"], "#geocon - 2026-09-17")
        self.assertEqual(kb_slack.list_unassigned(), [])
        self.assertEqual(self.docs, {})

    def test_unknown_client_and_unknown_key_are_refused(self):
        self._as("admin")
        key = self._queue_one()
        self.assertEqual(self.c.post("/kb/api/slack/assign", json={"key": key, "client_key": "nope"}).status_code, 404)
        self.assertEqual(self.c.post("/kb/api/slack/assign", json={"key": "slack-x", "client_key": "geocon"}).status_code, 404)


class AssignRendersNames(Rig):
    """The document a human files is permanent and nothing re-renders it, so the speaker names have
    to be right at WRITE time. Found 2026-09-18: the assign path read a cache that a fresh web
    process has never filled, and every speaker came out as `U0BFMVAG9T5`."""

    def test_assign_fetches_the_directory_when_the_cache_is_cold(self):
        self._as("admin")
        with self._slack(slack_api()):
            self.c.post("/kb/api/slack/sync", json={})          # queue it (unmapped -> waits)
        key = kb_slack.list_unassigned()[0]["key"]

        kb_slack._USERS.clear()                                 # a fresh instance: nothing cached
        kb_slack._USERS.update({"at": 0.0, "by_id": {}})
        with self._slack(slack_api()):
            r = self.c.post("/kb/api/slack/assign", json={"key": key, "client_key": "geocon"})
        self.assertTrue(r.get_json()["ok"], r.get_json())

        did = r.get_json()["doc"]["id"]
        body = self.docs[did]["body"]
        self.assertNotIn("U0", body, "raw Slack ids were written into a permanent document")
        self.assertIn("Charles", body)

    def test_a_directory_outage_does_not_lose_the_filing(self):
        self._as("admin")
        with self._slack(slack_api()):
            self.c.post("/kb/api/slack/sync", json={})
        key = kb_slack.list_unassigned()[0]["key"]
        with mock.patch.object(kb_slack, "users", side_effect=kb_slack.SlackError("users.list: down")):
            r = self.c.post("/kb/api/slack/assign", json={"key": key, "client_key": "geocon"})
        self.assertTrue(r.get_json()["ok"], "a directory outage must not block the filing")


class Mapping(Rig):
    def test_map_is_audited_and_never_refiles_by_itself(self):
        self._as("admin", "jerome@bidbrain.ai")
        # one doc already filed to cloudflare from this channel
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "cloudflare", "model", users_by_id=USERS)
        r = self.c.post("/kb/api/slack/map", json={"channel_id": "C0GEO", "name": "geocon", "client_key": "geocon"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(kb_slack.channel_client("C0GEO"), "geocon")
        [e] = self._of("slack_mapped")
        self.assertEqual((e["client"], e["guess"], e["channel"]), ("geocon", None, "geocon"))
        self.assertEqual(self.docs["slack-C0GEO-t1789635600-000000"]["client"], "cloudflare", "mapping must not move filed docs")
        # the explicit second step moves them
        r = self.c.post("/kb/api/slack/refile", json={"channel_id": "C0GEO"})
        self.assertEqual(r.get_json()["moved"], 1)
        self.assertEqual(self.docs["slack-C0GEO-t1789635600-000000"]["client"], "geocon")
        [mv] = self._of("slack_moved")
        self.assertEqual((mv["guess"], mv["client"]), ("cloudflare", "geocon"))
        self.assertEqual(self._of("slack_assigned"), [], "a move is not a confirmation")

    def test_agency_wide_is_a_real_mapping_and_null_clears(self):
        self._as("admin")
        self.assertTrue(self.c.post("/kb/api/slack/map", json={"channel_id": "C0GEN", "client_key": ""}).get_json()["ok"])
        self.assertEqual(kb_slack.channel_client("C0GEN"), "")
        self.assertTrue(self.c.post("/kb/api/slack/map", json={"channel_id": "C0GEN", "client_key": None}).get_json()["ok"])
        self.assertIsNone(kb_slack.channel_client("C0GEN"))
        self.assertEqual(self.c.post("/kb/api/slack/map", json={"channel_id": "C0GEN", "client_key": "nope"}).status_code, 404)

    def test_refile_needs_a_mapping(self):
        self._as("admin")
        self.assertEqual(self.c.post("/kb/api/slack/refile", json={"channel_id": "C0GEO"}).status_code, 400)


class Status(Rig):
    def test_status_lists_member_channels_with_their_mapping(self):
        self._as("admin")
        kb_slack.set_channel_client("C0GEO", "geocon", by="jerome@bidbrain.ai")
        with self._slack(slack_api()):
            j = self.c.get("/kb/api/slack/status").get_json()
        self.assertTrue(j["connected"] and j["events"])
        [c] = j["channels"]
        self.assertEqual((c["name"], c["mapped"], c["client"], c["mapped_by"]), ("geocon", True, "geocon", "jerome@bidbrain.ai"))

    def test_slack_being_down_is_named_not_a_500(self):
        self._as("admin")
        with self._slack(FakeSlack({"conversations.list": lambda p: {"ok": False, "error": "invalid_auth"}})):
            r = self.c.get("/kb/api/slack/status")
        self.assertEqual(r.status_code, 200)
        self.assertIn("invalid_auth", r.get_json()["channels_error"])


class Log(Rig):
    def test_log_is_slack_kinds_only_and_filterable(self):
        import kb_activity
        self._as("admin")
        with mock.patch.object(kb_activity, "recent", return_value=[
            {"kind": "slack_filed", "at": 1, "title": "a"}, {"kind": "meeting_filed", "at": 2, "title": "m"},
            {"kind": "search", "at": 3}, {"kind": "slack_queued", "at": 4, "title": "b"}]):
            j = self.c.get("/kb/api/slack/log").get_json()
            self.assertEqual([e["kind"] for e in j["events"]], ["slack_queued", "slack_filed"])
            self.assertEqual(j["counts"], {"slack_filed": 1, "slack_queued": 1})
            self.assertIn("slack_purged", j["kinds"])
            j2 = self.c.get("/kb/api/slack/log?kind=slack_filed").get_json()
            self.assertEqual([e["kind"] for e in j2["events"]], ["slack_filed"])
            self.assertEqual(j2["total"], 1, "total is the filtered view (the pill beside the heading)...")
            self.assertEqual(j2["counts"], {"slack_filed": 1, "slack_queued": 1}, "...counts describe the whole record (the filter chips)")

    def test_every_declared_slack_kind_is_actually_written_somewhere(self):
        import re, pathlib, kb_activity
        src = pathlib.Path(self.r.__file__).read_text(encoding="utf-8")
        written = set(re.findall(r'_audit\(\s*"([a-z_]+)"', src))
        self.assertEqual(set(kb_activity.GROUPS["slack"]) - written, set(), "declared but never written")


class Events(Rig):
    def _post(self, payload, secret="sekrit", headers=None):
        body = json.dumps(payload).encode()
        h = headers if headers is not None else sign(secret, body)
        return self.c.post("/slack/events", data=body, headers=dict(h, **{"Content-Type": "application/json"}))

    def test_url_verification_echoes_the_challenge(self):
        r = self._post({"type": "url_verification", "challenge": "abc123"})
        self.assertEqual(r.get_json(), {"challenge": "abc123"})

    def test_bad_signature_is_401_and_missing_secret_is_503(self):
        self.assertEqual(self._post({"type": "url_verification"}, secret="wrong").status_code, 401)
        with mock.patch.dict(os.environ, {"SLACK_SIGNING_SECRET": ""}):
            self.assertEqual(self._post({"type": "url_verification"}).status_code, 503)

    def test_a_message_event_resyncs_that_channel_and_a_retry_is_a_noop(self):
        kb_slack.set_channel_client("C0GEO", "geocon")
        ev = {"type": "event_callback", "event_id": "Ev1", "team_id": "T1",
              "event": {"type": "message", "channel": "C0GEO", "user": "U1", "text": "hi", "ts": ts(3600)}}
        with self._slack(slack_api()):
            r = self._post(ev)
            self.assertEqual(r.get_json()["resync"], "C0GEO")
            self.assertEqual(len(self.docs), 2)
            n = len(self.events)
            r2 = self._post(ev)                                      # Slack retried
        self.assertTrue(r2.get_json()["duplicate"])
        self.assertEqual(len(self.events), n)
        self.assertIn(f"{kb_store.PREFIX}/slack/inbox/Ev1.json", self.fs.objects)
        self.assertFalse(kb_slack.state().get("sync_in_progress"), "an event resync never flips the page-wide flag")

    def test_uninstall_purges_everything_and_records_it(self):
        kb_slack.set_channel_client("C0GEO", "geocon")
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "geocon", "channel", users_by_id=USERS)
        kb_slack.save_state({"sync_in_progress": False})
        deleted = []
        with mock.patch.object(kb_store, "delete_doc", deleted.append):
            r = self._post({"type": "event_callback", "event_id": "Ev9", "event": {"type": "app_uninstalled"}})
        self.assertEqual(r.get_json()["purge"], "started")
        self.assertEqual(deleted, ["slack-C0GEO-t1789635600-000000"])
        self.assertFalse([k for k in self.fs.objects if "/slack/" in k and not k.endswith("inbox/Ev9.json")] , "only the record of the uninstall itself may remain")
        [e] = self._of("slack_purged")
        self.assertEqual((e["note"], e["docs"]), ("app_uninstalled", 1))


if __name__ == "__main__":
    unittest.main()


class Lifecycle(Rig):
    def _post(self, payload):
        body = json.dumps(payload).encode()
        return self.c.post("/slack/events", data=body, headers=dict(sign("sekrit", body), **{"Content-Type": "application/json"}))

    def test_rename_follows_the_id_and_keeps_the_mapping(self):
        kb_slack.set_channel_client("C0GEO", "geocon", name="geocon", by="jerome@bidbrain.ai")
        kb_slack.save_state({"channels": {"C0GEO": {"name": "geocon", "last_ts": "1"}}})
        r = self._post({"type": "event_callback", "event_id": "Ev2", "event": {"type": "channel_rename", "channel": {"id": "C0GEO", "name": "geocon-ads"}}})
        self.assertEqual(r.get_json()["channel_change"], "channel_rename")
        self.assertEqual(kb_slack.state()["channels"]["C0GEO"]["name"], "geocon-ads")
        self.assertEqual(kb_slack.state()["channels"]["C0GEO"]["last_ts"], "1")      # watermark untouched
        cm = kb_slack.channel_map()["C0GEO"]
        self.assertEqual((cm["client"], cm["name"], cm["by"]), ("geocon", "geocon-ads", "jerome@bidbrain.ai"))
        [e] = self._of("slack_channel")
        self.assertEqual((e["note"], e["channel"]), ("channel_rename", "geocon-ads"))

    def test_someone_else_leaving_is_nothing_the_bot_leaving_marks_the_channel_gone(self):
        kb_slack.save_state({"team": {"user_id": "UB"}, "channels": {"C0GEO": {"name": "geocon"}}})
        self._post({"type": "event_callback", "event_id": "Ev3", "event": {"type": "member_left_channel", "channel": "C0GEO", "user": "U1"}})
        self.assertNotIn("gone", kb_slack.state()["channels"]["C0GEO"])
        self.assertEqual(self._of("slack_channel"), [])
        self._post({"type": "event_callback", "event_id": "Ev4", "event": {"type": "member_left_channel", "channel": "C0GEO", "user": "UB"}})
        self.assertEqual(kb_slack.state()["channels"]["C0GEO"]["gone"], "member_left_channel")

    def test_archive_marks_gone_but_deletes_nothing(self):
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "geocon", "channel", users_by_id=USERS)
        kb_slack.save_state({"channels": {"C0GEO": {"name": "geocon"}}})
        self._post({"type": "event_callback", "event_id": "Ev5", "event": {"type": "channel_archive", "channel": "C0GEO"}})
        self.assertEqual(kb_slack.state()["channels"]["C0GEO"]["gone"], "channel_archive")
        self.assertEqual(len(self.docs), 1, "a channel closing does not un-say what was said in it")


class CustomerAudience(Rig):
    def test_a_slack_document_never_reaches_a_customer_even_if_marked_client_visible(self):
        import kb_bridge
        metas = {"slack-C0GEO-d2026-09-17": {"id": "slack-C0GEO-d2026-09-17", "source": "slack", "kind": "conversation", "visibility": "client"},
                 "fathom-1": {"id": "fathom-1", "source": "fathom", "kind": "meeting", "visibility": "client"},
                 "brief-1": {"id": "brief-1", "source": "upload", "kind": "brief", "visibility": "client"}}
        res = {"excerpts": [{"document_id": k, "title": k, "passage": "text", "ord": 0} for k in metas], "semantic": True, "documents_searched": 3}
        with mock.patch.object(kb_index, "search", return_value=res), mock.patch.object(kb_index, "all_meta", return_value=metas):
            ret = kb_bridge.retrieve_for_client("geocon", [{"role": "user", "content": "what did we agree on the Search campaign pause?"}])
        self.assertEqual([p["doc_id"] for p in ret["passages"]], ["brief-1"])


class Observability(Rig):
    def test_observability_carries_a_slack_summary_beside_meetings(self):
        import kb_activity
        self._as("admin", "ian@100.digital")
        with mock.patch.object(kb_activity, "recent", return_value=[
                {"kind": "slack_filed", "by": "channel", "at": 1}, {"kind": "slack_filed", "by": "model", "at": 2},
                {"kind": "slack_queued", "at": 3}, {"kind": "slack_assigned", "agreed": False, "at": 4},
                {"kind": "slack_mapped", "at": 5}, {"kind": "meeting_filed", "at": 6}]), \
             mock.patch.object(kb_activity, "summarise", return_value={}):
            r = self.c.get(OBS_PATH)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:200])
        s = r.get_json()["slack"]
        self.assertEqual((s["filed"], s["by_channel"], s["waited"], s["confirmed"], s["overruled"], s["mapped"], s["total"]),
                         (2, 1, 1, 1, 1, 1, 5))
        self.assertEqual(s["auto_rate"], round(2 / 3, 3))
        self.assertEqual(r.get_json()["meetings"]["total"], 1)


class Memory(Rig):
    """S6-02: the people who spoke in a CONFIRMED conversation teach memory, as a meeting's external
    invitees do. A colleague never does; a mapping or a model filing never does."""

    def _mem(self, ck):
        import kb_memory
        return kb_memory.load(ck)

    def test_the_card_says_what_assign_will_remember_and_a_human_assign_learns_it(self):
        self._as("admin", "jerome@bidbrain.ai")
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]          # Sam (Geocon) + two colleagues spoke
        kb_slack.store_unassigned(conv, proposal={"client_key": "geocon", "confidence": 0.7}, users_by_id=USERS)
        [card] = kb_slack.list_unassigned()
        self.assertEqual(card["will_learn"], {"people": ["sam@geocon.com.au"], "domains": ["geocon.com.au"], "title": ""})
        with mock.patch.object(kb_slack, "_USERS", {"at": time.time(), "by_id": USERS}):
            r = self.c.post("/kb/api/slack/assign", json={"key": card["key"], "client_key": "geocon"})
        self.assertTrue(r.get_json()["ok"], r.get_json())
        mem = self._mem("geocon")
        self.assertIn("sam@geocon.com.au", mem["people"])
        self.assertIn("geocon.com.au", mem["domains"])
        self.assertNotIn("charles@100.digital", mem["people"], "a colleague is never learned as belonging to a client")
        [e] = self._of("slack_assigned")
        self.assertEqual(e["skipped"], "")

    def test_an_unticked_item_is_not_learned(self):
        self._as("admin", "jerome@bidbrain.ai")
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.store_unassigned(conv, proposal=None, users_by_id=USERS)
        with mock.patch.object(kb_slack, "_USERS", {"at": time.time(), "by_id": USERS}):
            r = self.c.post("/kb/api/slack/assign", json={"key": "slack-C0GEO-t1789635600-000000", "client_key": "geocon",
                                                          "skip": ["sam@geocon.com.au"]})
        self.assertTrue(r.get_json()["ok"])
        mem = self._mem("geocon")
        self.assertNotIn("sam@geocon.com.au", mem["people"])
        self.assertIn("geocon.com.au", mem["domains"], "only the unticked item is left out")
        self.assertEqual(self._of("slack_assigned")[0]["skipped"], "sam@geocon.com.au")

    def test_a_channel_mapping_and_a_model_filing_teach_nothing(self):
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "geocon", "channel", users_by_id=USERS)
        kb_slack.index_conversation(conv, "geocon", "model", users_by_id=USERS)
        self.assertEqual(self._mem("geocon")["people"], {})
        kb_slack.index_conversation(conv, "", "human", users_by_id=USERS)     # agency-wide teaches nothing either
        self.assertEqual(self._mem("geocon")["people"], {})

    def test_memory_then_matches_the_next_conversation_with_that_guest(self):
        """The payoff: after one confirmation, the ladder's memory rung recognises the guest and the
        next conversation in an UNMAPPED channel files without the model."""
        import kb_memory, kb_fathom
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "geocon", "human", users_by_id=USERS)
        nxt = kb_slack.group_conversations([{"type": "message", "user": "U9", "ts": ts(90000), "text": "Any update on the pause?"}],
                                           {"id": "C0OTHER", "name": "random", "is_private": False})[0]
        kind, ck, ev = kb_memory.match(kb_slack.as_meeting(nxt, USERS), kb_memory.load_all())
        self.assertEqual((kind, ck), ("assign", "geocon"))
        self.assertIn("sam@geocon.com.au seen on 1 confirmed meeting(s)", ev)
        with mock.patch.object(kb_fathom, "synthesise") as syn:
            r = kb_fathom.classify(kb_slack.as_meeting(nxt, USERS), {}, kb_memory.load_all(), CLIENTS)
        syn.assert_not_called()
        self.assertEqual((r["decision"], r["client_key"], r["assigned_by"]), ("assign", "geocon", "memory"))


class ProviderGuard(Rig):
    """S5-04: Slack-derived passages never reach a provider whose terms allow training on inputs
    (Kimi, read 2026-09-17), whatever model the person chose - and the answer says so."""

    def test_withhold_from_fires_only_when_a_slack_passage_was_retrieved(self):
        metas = {"slack-C0GEO-d1": {"source": "slack", "kind": "conversation"}, "brief-1": {"source": "upload", "kind": "brief"}}
        self.assertEqual(kb_slack.withhold_from([{"document_id": "brief-1"}], metas), ())
        self.assertEqual(kb_slack.withhold_from([{"document_id": "brief-1"}, {"document_id": "slack-C0GEO-d1"}], metas), ("kimi",))
        self.assertEqual(kb_slack.withhold_from([], metas), ())

    def test_stream_skips_an_excluded_provider_even_when_preferred(self):
        import kb_chat
        calls = []
        def impl(name):
            def f(prefix, messages):
                calls.append(name)
                yield ("token", "ok from " + name)
            return f
        with mock.patch.dict(kb_chat._IMPL, {"kimi": impl("kimi"), "gemini": impl("gemini"), "claude": impl("claude")}), \
             mock.patch.object(kb_chat, "configured", return_value=True), \
             mock.patch.object(kb_chat, "available", return_value=["kimi", "gemini", "claude"]):
            out = list(kb_chat.stream("p", [], prefer="kimi", exclude=("kimi",)))
            self.assertEqual(calls, ["gemini"])
            model = [p for k, p in out if k == "model"][0]
            self.assertEqual((model["provider"], model["withheld_from"]), ("gemini", ["kimi"]))
            # nothing excluded: the preference is honoured as before
            calls.clear()
            list(kb_chat.stream("p", [], prefer="kimi"))
            self.assertEqual(calls, ["kimi"])
            # everything excluded: a named refusal, not a silent fallback to nothing
            with self.assertRaises(kb_chat.ProviderError) as cm:
                list(kb_chat.stream("p", [], exclude=("kimi", "gemini", "claude")))
            self.assertIn("may not be shown this content", str(cm.exception))

    def test_ask_withholds_kimi_when_the_answer_draws_on_slack(self):
        import kb_chat, kb_settings
        self._as("admin", "jerome@bidbrain.ai")
        calls = []
        def impl(name):
            def f(prefix, messages):
                calls.append(name)
                yield ("token", "answer")
            return f
        slack_meta = {"id": "slack-C0GEO-d2026-09-17", "source": "slack", "kind": "conversation", "title": "#geocon - 2026-09-17",
                      "folder": "Slack/#geocon", "client": "geocon", "trust": "standard"}
        res = {"excerpts": [{"document_id": "slack-C0GEO-d2026-09-17", "title": slack_meta["title"], "folder": slack_meta["folder"],
                             "trust": "standard", "ord": 0, "passage_id": "p1", "passage": "[20:00] Charles: pause the Search campaign",
                             "found_by": ["keyword"], "score": 1.0, "keyword_rank": 1, "semantic_rank": None, "semantic_score": None}],
               "semantic": False, "semantic_error": "off", "scope": "all", "outcome": "hits", "client": "geocon",
               "documents_searched": 1, "unembedded_documents": 0, "ms": 3}
        with mock.patch.object(kb_index, "search", return_value=res), \
             mock.patch.object(kb_index, "all_meta", return_value={slack_meta["id"]: slack_meta}), \
             mock.patch.object(kb_index, "folder_counts", return_value={}), \
             mock.patch.object(kb_settings, "read", return_value={"model": "kimi", "speak_replies": False}), \
             mock.patch.dict(kb_chat._IMPL, {"kimi": impl("kimi"), "gemini": impl("gemini"), "claude": impl("claude")}), \
             mock.patch.object(kb_chat, "configured", return_value=True), \
             mock.patch.object(kb_chat, "available", return_value=["kimi", "gemini", "claude"]), \
             mock.patch.object(kb_store, "read_chat", return_value=None), mock.patch.object(kb_store, "write_chat"):
            r = self.c.post("/kb/ask", json={"q": "did we pause the Search campaign?", "client": "geocon"})
            body = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(calls, ["gemini"], "the person chose Kimi; Slack content overrides that for this one answer")
        self.assertIn('"withheld_from": ["kimi"]', body)
        [q] = self._of("question")
        self.assertEqual(q["withheld_from"], ["kimi"])

    def test_purge_check_reports_what_is_left(self):
        self._as("admin")
        conv = kb_slack.group_conversations([dict(PARENT)], CH)[0]
        kb_slack.index_conversation(conv, "geocon", "channel", users_by_id=USERS)
        kb_slack.save_state({"sync_in_progress": False})
        j = self.c.get("/kb/api/slack/purge-check").get_json()
        self.assertEqual((j["documents"], j["clean"]), (1, False))
        self.assertGreaterEqual(j["objects"], 1)
        with mock.patch.object(kb_store, "delete_doc", lambda did: self.docs.pop(did)):
            kb_slack.purge_all()
        j = self.c.get("/kb/api/slack/purge-check").get_json()
        self.assertEqual((j["documents"], j["objects"], j["clean"]), (0, 0, True))


class PrivateChannels(Rig):
    def test_sync_skips_private_channels_until_allowed_and_status_says_so(self):
        self._as("admin")
        kb_slack.set_channel_client("C0GEO", "geocon")
        kb_slack.set_channel_client("C0PRIV", "geocon")
        chans = [{"id": "C0GEO", "name": "geocon", "is_member": True, "is_private": False},
                 {"id": "C0PRIV", "name": "geocon-private", "is_member": True, "is_private": True}]
        with self._slack(slack_api(channels=chans)), mock.patch.object(kb_slack, "ALLOW_PRIVATE", False):
            self.c.post("/kb/api/slack/sync", json={})
            j = self.c.get("/kb/api/slack/status").get_json()
        st = kb_slack.state()
        self.assertEqual((st["last_counts"]["channels"], st["last_counts"]["skipped_private"]), (1, 1))
        self.assertFalse(any(k.startswith("slack-C0PRIV-") for k in self.docs), "nothing from the private channel was filed")
        by = {c["id"]: c for c in j["channels"]}
        self.assertEqual((by["C0GEO"]["readable"], by["C0PRIV"]["readable"], j["allow_private"]), (True, False, False))
        # switched on, the same channel is read
        with self._slack(slack_api(channels=chans)), mock.patch.object(kb_slack, "ALLOW_PRIVATE", True):
            self.c.post("/kb/api/slack/sync", json={})
        self.assertTrue(any(k.startswith("slack-C0PRIV-") for k in self.docs))

    def test_a_message_event_from_a_private_channel_is_ignored_by_default(self):
        kb_slack.save_state({"channels": {"C0PRIV": {"name": "geocon-private", "is_private": True}}})
        body = json.dumps({"type": "event_callback", "event_id": "Ev7", "event": {"type": "message", "channel": "C0PRIV", "ts": ts(0), "user": "U1", "text": "x"}}).encode()
        with mock.patch.object(kb_slack, "ALLOW_PRIVATE", False):
            r = self.c.post("/slack/events", data=body, headers=dict(sign("sekrit", body), **{"Content-Type": "application/json"}))
        self.assertEqual(r.get_json()["ignored"], "private channel")
        self.assertEqual(self.docs, {})
