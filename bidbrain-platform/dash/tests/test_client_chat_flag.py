"""K5-01: the per-client `client_chat` flag - store semantics, the gate, the console route."""
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import store as S  # noqa: E402

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
if HAVE_FLASK:
    import main  # noqa: E402


class StoreFlag(unittest.TestCase):
    def setUp(self):
        self.doc = {"clients": {"mongodb": {"name": "MongoDB"}, "cloudflare": {"name": "Cloudflare", "client_chat": True}},
                    "agencies": []}
        self.s = S.Store()
        self.p_load = mock.patch.object(self.s, "_load", side_effect=lambda: self.doc)
        self.p_save = mock.patch.object(self.s, "_save", side_effect=lambda d: self.doc.update(d))
        self.p_load.start()
        self.p_save.start()

    def tearDown(self):
        self.p_load.stop()
        self.p_save.stop()

    def test_absent_is_off_and_toggle_round_trips(self):
        self.assertFalse(self.s.get_client_chat("mongodb"))
        self.assertTrue(self.s.get_client_chat("cloudflare"))
        self.assertFalse(self.s.get_client_chat("nope"))
        self.assertTrue(self.s.set_client_chat("mongodb", True))
        self.assertTrue(self.s.get_client_chat("mongodb"))
        self.assertTrue(self.s.set_client_chat("mongodb", False))
        self.assertNotIn("client_chat", self.doc["clients"]["mongodb"])   # off == absent
        self.assertFalse(self.s.set_client_chat("nope", True))

    def test_super_state_carries_the_flag(self):
        st = self.s.get_super_state()
        by_key = {d["key"]: d for d in st["dashboards"]}
        self.assertTrue(by_key["cloudflare"]["client_chat"])
        self.assertFalse(by_key["mongodb"]["client_chat"])

    def test_external_agency_default_is_off_internal_on(self):
        self.assertFalse(S.agency_setting({"external": True, "slug": "x"}, "client_chat"))
        self.assertTrue(S.agency_setting({"slug": "transmission"}, "client_chat"))
        self.assertTrue(S.agency_setting(None, "client_chat"))


@unittest.skipUnless(HAVE_FLASK, "flask not importable")
class GateAndRoute(unittest.TestCase):
    def setUp(self):
        main.app.config["TESTING"] = True
        self.c = main.app.test_client()
        self.flags = {"cloudflare": True, "mongodb": False}
        self.patches = [
            mock.patch.object(main, "CLIENT_CHAT_ENABLED", True),      # master switch is OFF by default (2026-09-15)
            mock.patch.object(main.store, "_all_clients", return_value={"cloudflare": {}, "mongodb": {}}),
            mock.patch.object(main.store, "get_client_chat", side_effect=lambda k: self.flags.get(k, False)),
            mock.patch.object(main.store, "set_client_chat", side_effect=lambda k, on: self.flags.__setitem__(k, on) or True),
            mock.patch.object(main.store, "get_client", side_effect=lambda k: {"url": "https://x"} if k in self.flags else None),
            mock.patch.object(main.store, "active_client_keys", return_value=["cloudflare", "mongodb"]),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def _as(self, kind, **extra):
        with self.c.session_transaction() as s:
            s.clear()
            s["kind"] = kind
            s.update(extra)

    def test_gate_client_session_own_dashboard_only_when_flag_on(self):
        with main.app.test_request_context():
            from flask import session
            session["kind"] = "client"
            session["client_key"] = "cloudflare"
            self.assertTrue(main._client_chat_allowed("cloudflare"))
            self.assertFalse(main._client_chat_allowed("mongodb"))       # flag off
            session["client_key"] = "mongodb"
            self.assertFalse(main._client_chat_allowed("cloudflare"))    # not their dashboard

    def test_gate_staff_can_preview_external_agency_never(self):
        with main.app.test_request_context():
            from flask import session
            session["kind"] = "superadmin"
            self.assertTrue(main._client_chat_allowed("cloudflare"))
            session.clear()
            session["kind"] = "agency"
            session["agency_slug"] = "extrablack"
            with mock.patch.object(main.store, "get_agency", return_value={"slug": "extrablack", "external": True,
                                                                           "client_keys": ["cloudflare"]}):
                self.assertFalse(main._client_chat_allowed("cloudflare"))

    def test_route_superadmin_only(self):
        self._as("admin", email="ian@100.digital")
        self.assertEqual(self.c.post("/super/api/client-chat", json={"key": "mongodb", "on": True}).status_code, 403)
        self._as("superadmin")
        r = self.c.post("/super/api/client-chat", json={"key": "mongodb", "on": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertTrue(self.flags["mongodb"])
        r = self.c.post("/super/api/client-chat", json={"key": "mongodb", "on": False})
        self.assertFalse(self.flags["mongodb"])
        self.assertEqual(self.c.post("/super/api/client-chat", json={"key": "nope", "on": True}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
