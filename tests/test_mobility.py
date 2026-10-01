"""Testy M0 mobility — REST backend dla apki Astro Mobilne (bez LLM/audio; mock backendu)."""

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from astro.mobility import chat, knowledge
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


def _make_learned_db(path: Path) -> None:
    """Mini baza `learned` — schema zgodna z memory.store."""
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE learned (id INTEGER PRIMARY KEY, ts REAL, topic TEXT, title TEXT, "
        "text TEXT, source TEXT, verified INTEGER, confidence REAL, url TEXT, qkey TEXT)")
    rows = [
        (1, "fakt", "stolica polski", "Stolica Polski to Warszawa.", "facts"),
        (2, "fakt", "stolica francji", "Stolica Francji to Paryz.", "facts"),
        (3, "obyczajowe", "dzien dobry", "Dzien dobry! Milo mi Ciebie slychec.", "bielik"),
        (4, "smieci", "urwane", "Odpowiedz ucina sie w polowie zdania...", "remote"),
    ]
    conn.executemany(
        "INSERT INTO learned(id, ts, topic, title, text, source) VALUES(?,0,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class TestKnowledge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "memory.db"
        _make_learned_db(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pack_skips_truncated(self):
        items = knowledge.pack(self.db)
        self.assertEqual([i["id"] for i in items], [1, 2, 3])
        self.assertEqual(items[0]["q"], "stolica polski")
        self.assertEqual(items[0]["a"], "Stolica Polski to Warszawa.")

    def test_latest_id_and_delta(self):
        self.assertEqual(knowledge.latest_id(self.db), 4)
        self.assertEqual([i["id"] for i in knowledge.delta(self.db, 2)], [3])

    def test_delta_since_zero_is_pack(self):
        self.assertEqual(knowledge.delta(self.db, 0, 10), knowledge.pack(self.db)[:10])

    def test_missing_db_is_empty(self):
        brak = Path(self._tmp.name) / "nie_ma.db"
        self.assertEqual(knowledge.pack(brak), [])
        self.assertEqual(knowledge.delta(brak, 5), [])
        self.assertEqual(knowledge.latest_id(brak), 0)

    def test_context_returns_knowledge_delta(self):
        self._tmp2 = tempfile.TemporaryDirectory()
        app = create_app(db_path=Path(self._tmp2.name) / "m.db", token=TOKEN,
                         knowledge_db=self.db)
        app.config["TESTING"] = True
        try:
            client = app.test_client()
            auth = {"Authorization": f"Bearer {SECRET}"}
            # domyślnie (bez parametru `knowledge`) — regresja: Flask zwraca default
            # bez konwersji type, więc wiedza musi i tak być włączona
            body = client.get("/context", headers=auth).get_json()
            self.assertEqual([i["id"] for i in body["knowledge_delta"]], [1, 2, 3])
            self.assertEqual(body["knowledge_latest"], 4)
            body1 = client.get("/context?knowledge=1", headers=auth).get_json()
            self.assertEqual([i["id"] for i in body1["knowledge_delta"]], [1, 2, 3])
            d = client.get("/context?kdelta=2", headers=auth).get_json()
            self.assertEqual([i["id"] for i in d["knowledge_delta"]], [3])
            for off in ("0", "false"):
                none = client.get(f"/context?knowledge={off}", headers=auth).get_json()
                self.assertNotIn("knowledge_delta", none)
            pack = client.get("/knowledge", headers=auth).get_json()
            self.assertEqual(pack["count"], 3)
            self.assertEqual(pack["knowledge_latest"], 4)
        finally:
            app.config["STORE"].close()
            self._tmp2.cleanup()


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
