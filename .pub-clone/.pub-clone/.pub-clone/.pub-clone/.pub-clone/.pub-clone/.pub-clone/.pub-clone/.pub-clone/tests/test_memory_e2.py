"""Testy pamięci E2 (wektory, write-back, dryf lekcji, profil)."""

import os
import tempfile
import unittest

from astro import memory


def tmp_memory(embedder=None):
    db = os.path.join(tempfile.mkdtemp(), "mem.db")
    return memory.Memory(db, embedder=embedder)


def fake_embed(text):
    t = (text or "").lower()
    return [1.0, 0.0] if "kaw" in t else [0.0, 1.0]


class TestVectors(unittest.TestCase):
    def test_vector_search(self):
        mem = tmp_memory(embedder=fake_embed)
        mem.remember("użytkownik lubi kawę")
        mem.remember("użytkownik lubi herbatę")
        hits = mem.search("kawa")
        self.assertTrue(hits)
        self.assertIn("kawę", hits[0])


class TestWriteBack(unittest.TestCase):
    SAMPLE = ("Wyniki (duckduckgo):\n"
              "1. [duckduckgo] Python dokumentacja\n   https://docs.python.org/3/\n"
              "   oficjalna dokumentacja jezyka Python\n"
              "2. [bing] Spam\n   https://pornhub.com/x\n"
              "   jakis dlugi opis ktory ma ponad dwadziescia znakow\n")

    def test_learn_from_web(self):
        mem = tmp_memory()
        n = mem.learn_from_web("python", self.SAMPLE)
        self.assertEqual(n, 1)
        self.assertEqual(mem.learned_verified_count(), 1)
        row = mem.con.execute("SELECT url FROM learned WHERE source='web'").fetchone()
        self.assertIn("docs.python.org", row["url"])

    def test_no_results(self):
        mem = tmp_memory()
        self.assertEqual(mem.learn_from_web("x", "brak połączenia z siecią"), 0)


class TestLessonDrift(unittest.TestCase):
    def test_drift_removes_newer_contradiction(self):
        mem = tmp_memory()
        mem.add_lesson("kopiuj pliki przez rsync")
        mem.add_lesson("nie kopiuj pliki przez rsync")
        removed = mem.review_lesson_drift()
        self.assertEqual(len(removed), 1)
        self.assertEqual(mem.lesson_count(), 1)

    def test_no_false_positive(self):
        mem = tmp_memory()
        mem.add_lesson("używaj rsync do backupu")
        mem.add_lesson("sprawdzaj wolne miejsce")
        self.assertEqual(mem.review_lesson_drift(), [])
        self.assertEqual(mem.lesson_count(), 2)


class TestProfile(unittest.TestCase):
    def test_set_name_location(self):
        mem = tmp_memory()
        mem.set_name("Michał")
        mem.set_location("Poznań, ul. Byka 1")
        profile = " ".join(mem.profile())
        self.assertIn("Michał", profile)
        self.assertIn("Byka 1", profile)

    def test_set_name_replaces(self):
        mem = tmp_memory()
        mem.set_name("Adam")
        mem.set_name("Michał")
        names = [m for m in mem.all_memories() if "imię" in m]
        self.assertEqual(len(names), 1)
        self.assertIn("Michał", names[0])


if __name__ == "__main__":
    unittest.main()
