"""Testy ingest — nauka z podróży (bez embeddera, na :memory:). unittest dla run_tests.py."""

import tempfile
import unittest
from pathlib import Path

from astro.memory.store import Memory
from astro.mobility import ingest
from astro.mobility.store import MobilityStore


class TestIngest(unittest.TestCase):
    def _store(self, tmp):
        return MobilityStore(Path(tmp) / "m.db")

    def test_ingest_episodes_do_trajectorii(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.upsert_record("e1", "episodes", '{"opis":"wycieczka w góry"}',
                                "2026-10-01T10:00:00Z", source="phone")
            store.upsert_record("l1", "lessons", '{"temat":"sieci komputerowe"}',
                                "2026-10-01T11:00:00Z", source="phone")
            store.upsert_record("n1", "note", '{"text":"kup mleko"}',
                                "2026-10-01T12:00:00Z", source="phone")

            memory = Memory(":memory:", embedder=None)
            stats = ingest.ingest(store, memory)
            self.assertEqual(stats["episode"], 1)
            self.assertEqual(stats["lesson"], 1)
            self.assertEqual(stats["note"], 1)

            trajs = memory.trajectories(limit=10)
            kinds = {t["kind"] for t in trajs}
            self.assertEqual(kinds, {"phone_episode", "phone_lesson", "phone_note"})
            goals = {t["goal"] for t in trajs}
            self.assertIn("wycieczka w góry", goals)
            self.assertIn("kup mleko", goals)

            stats2 = ingest.ingest(store, memory)
            self.assertEqual(sum(stats2.values()), 0)
            self.assertEqual(len(memory.trajectories(limit=10)), 3)
            store.close()

    def test_ingest_dry_run_nie_zapisuje(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            store.upsert_record("e1", "episodes", '{"opis":"test"}',
                                "2026-10-01T10:00:00Z", source="phone")
            stats = ingest.ingest(store, None, dry_run=True)
            self.assertEqual(stats["episode"], 1)
            row = store._conn.execute(
                "SELECT ingested FROM phone_records WHERE id='e1'").fetchone()
            self.assertEqual(row[0], 0)
            store.close()

    def test_goal_fallback_dla_nie_json(self):
        goal, text = ingest._goal_and_text("zwykły tekst bez jsona")
        self.assertEqual(goal, "zwykły tekst bez jsona")
        self.assertEqual(text, "zwykły tekst bez jsona")


if __name__ == "__main__":
    unittest.main()