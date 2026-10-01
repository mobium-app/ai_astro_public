"""Testy notify — push przypomnień przez ntfy (mock serwera). unittest."""

import http.server
import tempfile
import threading
import unittest
from pathlib import Path

from astro.mobility import notify
from astro.mobility.store import MobilityStore


class _NtfyMock:
    def __init__(self):
        self.received = []

    def _make_handler(self):
        ntfy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                ntfy.received.append((self.path, body))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        return Handler

    def __enter__(self):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), self._make_handler())
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()


class TestNotify(unittest.TestCase):
    def test_due_reminders_wyslane_i_oznaczone(self):
        with tempfile.TemporaryDirectory() as tmp, _NtfyMock() as ntfy:
            store = MobilityStore(Path(tmp) / "m.db")
            store._conn.execute(
                "INSERT INTO reminders(id,text,when_ts,done,version,updated_at,source) "
                "VALUES('n1','kup mleko',?,0,1,'2026-10-01T00:00:00Z','phone')",
                (str(time() - 60),))
            store._conn.commit()

            result = notify.notify(store, "test-topic",
                                   base=f"http://127.0.0.1:{ntfy.port}")
            self.assertEqual(result["count"], 1)
            self.assertEqual(ntfy.received[0][1], "kup mleko")
            row = store._conn.execute(
                "SELECT done FROM reminders WHERE id='n1'").fetchone()
            self.assertEqual(row[0], 1)
            store.close()

    def test_nic_do_wyslania(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MobilityStore(Path(tmp) / "m.db")
            result = notify.notify(store, "test-topic", dry_run=True)
            self.assertEqual(result["count"], 0)
            store.close()

    def test_przyszle_przypomnienie_nie_wyslane(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MobilityStore(Path(tmp) / "m.db")
            store._conn.execute(
                "INSERT INTO reminders(id,text,when_ts,done,version,updated_at,source) "
                "VALUES('n1','jutro',?,0,1,'2026-10-01T00:00:00Z','phone')",
                (str(time() + 3600),))
            store._conn.commit()
            result = notify.notify(store, "test-topic", dry_run=True)
            self.assertEqual(result["count"], 0)
            store.close()

    def test_domyslny_topik(self):
        topic = notify.default_topic()
        self.assertTrue(topic.startswith("astro-mob-"))
        self.assertEqual(len(topic), len("astro-mob-") + 10)


from time import time  # noqa: E402


if __name__ == "__main__":
    unittest.main()