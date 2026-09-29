"""Testy pamięci (nowy memory.db + import kuratorowanej wiedzy)."""

import os
import tempfile
import unittest

from astro import memory


def tmp_memory():
    db = os.path.join(tempfile.mkdtemp(), "mem.db")
    return memory.Memory(db)


class TestRecall(unittest.TestCase):
    def test_remember_search(self):
        mem = tmp_memory()
        mem.remember("użytkownik lubi kawę")
        hits = mem.search("kawa")
        self.assertTrue(any("kawę" in h for h in hits))

    def test_profile(self):
        mem = tmp_memory()
        mem.remember("użytkownik ma na imię Michał")
        self.assertTrue(any("Michał" in p for p in mem.profile()))


class TestCurated(unittest.TestCase):
    def test_import_counts(self):
        mem = tmp_memory()
        stats = memory.import_curated(mem)
        self.assertGreater(stats["facts"], 400)
        self.assertGreater(stats["first_aid"], 80)
        self.assertEqual(mem.learned_verified_count(), stats["added"])

    def test_facts_answer(self):
        ans = memory.offline_facts_answer("co to jest inflacja")
        self.assertTrue(ans and "inflac" in ans.lower())

    def test_first_aid(self):
        ans = memory.first_aid_reply("oparzyłem rękę")
        self.assertTrue(ans)


class TestLearning(unittest.TestCase):
    def test_lessons(self):
        mem = tmp_memory()
        mem.add_lesson("nie usuwaj plików bez potwierdzenia")
        self.assertEqual(mem.lesson_count(), 1)
        self.assertEqual(len(mem.recent_lessons()), 1)

    def test_trajectories(self):
        mem = tmp_memory()
        mem.add_trajectory("plan", "sprawdź dysk", steps=[{"command": "df -h"}], ok=True)
        mem.add_trajectory("plan", "sprawdź dysk", steps=[{"command": "df -h"}], ok=True)
        self.assertEqual(mem.trajectory_count("plan"), 1)

    def test_episode(self):
        mem = tmp_memory()
        mem.add_episode("ile miejsca", "wolne 10 GB", ["system_info"], ok=True)
        self.assertEqual(mem.trajectory_count("episode"), 1)

    def test_plans(self):
        mem = tmp_memory()
        steps = [{"command": "df -h"}]
        mem.record_plan_result("sprawdź dysk", steps, success=True)
        plan = mem.find_plan("sprawdź dysk")
        self.assertIsNotNone(plan)
        self.assertEqual(plan["steps"], steps)

    def test_unknowns(self):
        mem = tmp_memory()
        mem.record_unknown("zrób coś dziwnego")
        mem.record_unknown("zrób coś dziwnego")
        self.assertEqual(mem.unknown_count(), 1)
        self.assertEqual(mem.top_unknowns()[0][1], 2)
        self.assertEqual(mem.delete_unknown("zrób coś dziwnego"), 1)
        self.assertEqual(mem.unknown_count(), 0)


if __name__ == "__main__":
    unittest.main()


class TestTrajCacheLRU(unittest.TestCase):
    def test_lru_evicts_oldest(self):
        from unittest import mock
        from astro import config
        mem = tmp_memory()
        with mock.patch.object(config, "TRAJ_CACHE_MAX", 2):
            mem._cache_lru(mem._traj_cache, "a", 1)
            mem._cache_lru(mem._traj_cache, "b", 2)
            mem._cache_lru(mem._traj_cache, "c", 3)
        self.assertEqual(list(mem._traj_cache.keys()), ["b", "c"])
        mem._cache_lru(mem._traj_cache, "b", 2)
        self.assertEqual(list(mem._traj_cache.keys()), ["c", "b"])
