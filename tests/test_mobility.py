"""Testy M0 mobility — REST backend dla apki Astro Mobilne (bez LLM/audio; mock backendu)."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astro.mobility import chat
from astro.mobility.auth import check_token
from astro.mobility.server import create_app
from astro.mobility.store import MobilityStore

SECRET = "sekret-test-mobility"
TOKEN = hashlib.sha256(SECRET.encode()).hexdigest()


class FakeReply:
    def __init__(self, text):
        self.text = text


class FakeBackend:
    name = "fake"

    def run(self, messages, **kwargs):
        return FakeReply(f"Echo: {messages[-1]['content']}")


class MobilityTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "mobility.db"
        self.app = create_app(db_path=self.db, token=TOKEN)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        self.app.config["STORE"].close()
        self._tmp.cleanup()

    def headers(self, token=SECRET):
        return {"Authorization": f"Bearer {token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers(), **kw)

    def post(self, path, payload):
        return self.client.post(path, json=payload, headers=self.headers())


class TestAuth(MobilityTestCase):
    def test_auth_required(self):
        self.assertEqual(self.client.get("/context").status_code, 401)
        self.assertEqual(self.client.get("/context", headers=self.headers("zły")).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.get("/context").status_code, 200)

    def test_check_token(self):
        digest = hashlib.sha256(b"abc").hexdigest()
        self.assertTrue(check_token("Bearer abc", digest))
        self.assertFalse(check_token("Bearer abc", hashlib.sha256(b"inny").hexdigest()))
        self.assertFalse(check_token(None, digest))
        self.assertFalse(check_token("abc", digest))


class TestHealth(MobilityTestCase):
    def test_health(self):
        body = self.client.get("/health").get_json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["server_version"], 0)
        self.assertIn("counts", body)


class TestSyncDelta(MobilityTestCase):
    def test_push_pull_delta(self):
        r = self.post("/episodes", {"id": "e1", "content": '{"opis":"test"}'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["version"], 1)

        r = self.post("/lessons", {"id": "l1", "content": '{"temat":"x"}'})
        self.assertEqual(r.get_json()["version"], 2)

        ctx = self.get("/context?since=1").get_json()
        self.assertEqual([x["id"] for x in ctx["records"]], ["l1"])
        self.assertEqual(ctx["server_version"], 2)

        ctx0 = self.get("/context?since=0").get_json()
        self.assertEqual(len(ctx0["records"]), 2)

    def test_id_required(self):
        self.assertEqual(self.post("/episodes", {"content": "{}"}).status_code, 400)

    def test_lww_last_write_wins(self):
        self.post("/episodes", {"id": "e1", "content": '{"v":1}'})
        self.post("/episodes", {"id": "e1", "content": '{"v":2}'})
        ctx = self.get("/context?since=0").get_json()
        self.assertEqual(len(ctx["records"]), 1)
        self.assertEqual(ctx["records"][0]["content"], '{"v":2}')

    def test_stale_version_ignored(self):
        self.post("/episodes", {"id": "e1", "content": '{"version":5}'})
        self.post("/episodes", {"id": "e1", "content": '{"version":2}'})
        ctx = self.get("/context?since=0").get_json()
        self.assertEqual(ctx["records"][0]["content"], '{"version":5}')


class TestRemember(MobilityTestCase):
    def test_remember_and_due(self):
        self.post("/remember", {"id": "n1", "content": '{"text":"kup mleko"}'})
        due = self.get("/remember?due=1").get_json()
        self.assertTrue(any(i["id"] == "n1" for i in due["items"]))


class TestChat(MobilityTestCase):
    def test_chat_uses_backend(self):
        with mock.patch.object(chat.registry, "choose",
                               return_value=FakeBackend()):
            resp = self.post("/chat", {"messages": [{"role": "user", "content": "hej"}]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["reply"], "Echo: hej")

    def test_chat_validation(self):
        self.assertEqual(self.post("/chat", {"messages": []}).status_code, 400)
        self.assertEqual(
            self.post("/chat", {"messages": [{"role": "bad", "content": "x"}]}).status_code, 400)
        self.assertEqual(self.post("/chat", {}).status_code, 400)


class TestStore(MobilityTestCase):
    def test_store_counts(self):
        store = MobilityStore(self.db)
        store.upsert_record("a", "episode", "{}", "2026-10-01T00:00:00Z")
        self.assertEqual(store.counts()["phone_records"], 1)
        self.assertEqual(store.counts()["reminders"], 0)
        store.close()


if __name__ == "__main__":
    unittest.main()
