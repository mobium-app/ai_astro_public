"""Testy ingestu bazy Q&A i retrieval embeddingowego `learned`."""

import json
import os
import tempfile
import unittest

from astro.memory import Memory
from astro.scripts.ingest_qa import load_records, norm


class FakeEmbedder:
    """Deterministyczny embedder: dziedzina -> oś. Tło -> własna oś (ortogonalna)."""

    def __call__(self, text):
        t = (text or "").lower()
        if "antybiot" in t:
            return [1.0, 0.0, 0.0]
        if "rekuren" in t:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class TestLoadRecords(unittest.TestCase):
    def test_new_schema(self):
        data = {"tematy": [{"tematyka_glowna": "Kat", "nazwa": "Sub", "qa": [
            {"pytanie": "Co to jest X?", "odpowiedz": "X to rzecz."},
            {"pytanie": "Co to jest Y?", "odpowiedz": "Y to inna rzecz."}]}]}
        path = os.path.join(tempfile.mkdtemp(), "q.json")
        json.dump(data, open(path, "w", encoding="utf-8"))
        recs = load_records(path)
        self.assertEqual(recs[0][0], "Kat")
        self.assertEqual(recs[0][1], "Sub")
        self.assertEqual(len(recs), 2)


class TestSemanticRetrieval(unittest.TestCase):
    def setUp(self):
        self.mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"), embedder=FakeEmbedder())
        self.mem.add_learned("m", "Jak działają antybiotyki?",
                             "Antybiotyki działają na bakterie, nie na wirusy.", source="qa")
        self.mem.add_learned("m", "Co to jest rekurencja?",
                             "Rekurencja to funkcja wywołująca samą siebie.", source="qa")

    def test_hits_right_entry(self):
        self.assertIn("Antybiotyki", self.mem.best_learned("Jak działają antybiotyki?"))
        self.assertIn("Rekurencja", self.mem.best_learned("Co to jest rekurencja?"))

    def test_no_false_positive_on_unrelated(self):
        # zapytanie o inną dziedzinę nie może zwrócić antybiotyków/rekurencji
        self.assertIsNone(self.mem.best_learned("Co to jest fotosynteza?"))

    def test_hybrid_prefers_lexical_grounding(self):
        # Dwa wpisy o IDENTYCZNYM podobieństwie semantycznym — wygrywa ten dzielący słowo
        # z pytaniem (rdzeń), a nie ślepo pierwszy z listy.
        class SameAxisEmbedder:
            def __call__(self, text):
                return [1.0, 0.0, 0.0]

        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"), embedder=SameAxisEmbedder())
        mem.add_learned("m", "Co to jest rower?",
                        "Rower to pojazd napędzany siłą mięśni.", source="qa")
        mem.add_learned("m", "Co to jest samochod?",
                        "Samochod to pojazd z silnikiem spalinowym.", source="qa")
        self.assertIn("Rower", mem.best_learned("rower pytanie"))

    def test_hybrid_recovers_borderline_with_lexical_support(self):
        # Trafienie nieco poniżej starego progu (0,80), ale z pokryciem słów pytania -> przyjęte.
        class VecEmbedder:
            def __init__(self, mapping):
                self.mapping = mapping

            def __call__(self, text):
                return self.mapping.get((text or "").strip().lower(), [0.0, 0.0, 1.0])

        emb = VecEmbedder({
            "rower pytanie": [1.0, 0.0, 0.0],
            "co to jest rower?": [0.75, 0.6614378277661477, 0.0],   # cos 0,75
            "co to jest samochod?": [0.82, 0.5723637183570038, 0.0],  # cos 0,82
        })
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"), embedder=emb)
        mem.add_learned("m", "Co to jest rower?",
                        "Rower to pojazd napędzany siłą mięśni.", source="qa")
        mem.add_learned("m", "Co to jest samochod?",
                        "Samochod to pojazd z silnikiem spalinowym.", source="qa")
        self.assertIn("Rower", mem.best_learned("rower pytanie"))

    def test_hybrid_rejects_strong_semantic_without_lexical(self):
        # Silne podobieństwo, brak wspólnych słów, poniżej progu STRONG -> odmowa (mniej pomyłek).
        class VecEmbedder:
            def __init__(self, mapping):
                self.mapping = mapping

            def __call__(self, text):
                return self.mapping.get((text or "").strip().lower(), [0.0, 0.0, 1.0])

        emb = VecEmbedder({"rower pytanie": [1.0, 0.0, 0.0],
                           "co to jest samochod?": [0.82, 0.5723637183570038, 0.0]})
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m.db"), embedder=emb)
        mem.add_learned("m", "Co to jest samochod?",
                        "Samochod to pojazd z silnikiem spalinowym.", source="qa")
        self.assertIsNone(mem.best_learned("rower pytanie"))

    def test_vector_backfill(self):
        mem = Memory(os.path.join(tempfile.mkdtemp(), "m2.db"))
        mem.add_learned("m", "Jak działają antybiotyki?", "Antybiotyki działają na bakterie.",
                        source="qa")
        self.assertEqual(mem.learned_vector_count(), 0)
        mem.embedder = FakeEmbedder()
        n = mem.backfill_learned_vectors()
        self.assertEqual(n, 1)
        self.assertEqual(mem.learned_vector_count(), 1)


if __name__ == "__main__":
    unittest.main()


class TestCurriculumNormalization(unittest.TestCase):
    def test_new_schema_to_categories(self):
        from astro.scripts.curriculum_check import load_curriculum
        data = {"tematy": [{"tematyka_glowna": "Kat", "nazwa": "Sub",
                            "qa": [{"pytanie": "Co to jest X?", "odpowiedz": "X."}]}]}
        cats = load_curriculum(data)
        self.assertEqual(cats[0]["name"], "Kat")
        self.assertEqual(cats[0]["topics"][0]["name"], "Sub")
        self.assertEqual(cats[0]["topics"][0]["subtopics"], ["Co to jest X?"])

    def test_old_schema_passthrough(self):
        from astro.scripts.curriculum_check import load_curriculum
        data = {"categories": [{"name": "C", "topics": [{"name": "T"}]}]}
        self.assertEqual(load_curriculum(data), data["categories"])
