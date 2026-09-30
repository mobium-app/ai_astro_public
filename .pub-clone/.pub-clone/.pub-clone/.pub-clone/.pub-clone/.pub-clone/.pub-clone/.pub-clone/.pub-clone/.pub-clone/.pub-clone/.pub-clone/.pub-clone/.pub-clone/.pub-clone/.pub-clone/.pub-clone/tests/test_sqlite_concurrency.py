"""Współdzielony SQLite (WAL + busy_timeout): usługa, pętla wiedzy i batch piszą równolegle
do tej samej bazy bez „database is locked"."""

import os
import tempfile
import threading
import unittest

from astro import memory


def tmp_db():
    return os.path.join(tempfile.mkdtemp(), "mem.db")


class TestSqliteShared(unittest.TestCase):
    def test_pragmas_wal_and_busy_timeout(self):
        mem = memory.Memory(tmp_db())
        mode = str(mem.con.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        self.assertEqual(mode, "wal")
        busy = int(mem.con.execute("PRAGMA busy_timeout").fetchone()[0])
        self.assertGreaterEqual(busy, 1000)

    def test_concurrent_writers_no_lock_error(self):
        db = tmp_db()
        errors = []

        def writer(prefix, n):
            m = memory.Memory(db)
            try:
                for i in range(n):
                    m.add_session_turn(f"{prefix}-u{i}", f"{prefix}-a{i}")
            except Exception as e:  # noqa: BLE001 - raportujemy dowolny błąd współbieżności
                errors.append(repr(e))
            finally:
                m.con.close()

        threads = [threading.Thread(target=writer, args=(f"w{k}", 40)) for k in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        check = memory.Memory(db)
        count = check.con.execute("SELECT COUNT(*) c FROM session_turns").fetchone()["c"]
        self.assertEqual(count, 120)


if __name__ == "__main__":
    unittest.main()
