"""Testy Fazy 3 wizji: wiek/płeć, affect z emocji, zdarzenia w rozmowie, OCR w kontekście."""

import json
import tempfile
import unittest
from unittest import mock

from astro import config, memory
from astro.affect import appraisal
from astro.core import must_have
from astro.tools import ToolContext, registry
from astro.vision import engine, scene


class TestAgeGender(unittest.TestCase):
    def test_model_metadata(self):
        self.assertEqual(len(engine.AGE_RANGES), 8)
        self.assertEqual(len(engine.GENDERS), 2)
        for r in engine.AGE_RANGES:
            self.assertIn(r, engine.AGE_RANGES_PL)

    def test_describe_age_gender(self):
        out = {"persons": 1, "known": [], "unknown": 0, "objects": [], "expression": "",
               "age_gender": {"age": "25-32", "gender": "kobieta",
                              "age_score": 0.7, "gender_score": 0.99},
               "brightness": 120}
        text = scene.describe(out)
        self.assertIn("kobieta", text)
        self.assertIn("25", text)
        self.assertIn("32", text)

    def test_describe_age_gender_man(self):
        out = {"persons": 1, "known": [], "unknown": 0, "objects": [], "expression": "",
               "age_gender": {"age": "60-100", "gender": "mężczyzna",
                              "age_score": 0.6, "gender_score": 0.9},
               "brightness": 120}
        text = scene.describe(out)
        self.assertIn("mężczyzna", text)
        self.assertIn("60", text)

    def test_describe_without_age_gender(self):
        out = {"persons": 1, "known": [], "unknown": 0, "objects": [], "expression": "",
               "age_gender": None, "brightness": 120}
        text = scene.describe(out)
        self.assertNotIn("w wieku", text)


class TestAffectFromVision(unittest.TestCase):
    def test_expression_pad_happy(self):
        p, a, d = appraisal.expression_pad("happy")
        self.assertGreater(p, 0.0)
        self.assertGreater(a, 0.0)

    def test_expression_pad_sad(self):
        p, a, _d = appraisal.expression_pad("sad")
        self.assertLess(p, 0.0)

    def test_expression_pad_angry_arousal(self):
        _p, a, _d = appraisal.expression_pad("angry")
        self.assertGreater(a, 0.0)

    def test_expression_pad_neutral_and_unknown(self):
        self.assertEqual(appraisal.expression_pad("neutral"), (0.0, 0.0, 0.0))
        self.assertEqual(appraisal.expression_pad(""), (0.0, 0.0, 0.0))
        self.assertEqual(appraisal.expression_pad("nieznana"), (0.0, 0.0, 0.0))

    def test_expression_pad_strength(self):
        p1, _, _ = appraisal.expression_pad("happy", 1.0)
        p2, _, _ = appraisal.expression_pad("happy", 0.5)
        self.assertAlmostEqual(p2, p1 * 0.5)

    def test_apply_to_affect_state(self):
        from astro.affect.affect import AffectState
        state = AffectState(mood=(0.0, 0.0, 0.0), emotion=(0.0, 0.0, 0.0))
        state.apply(*appraisal.expression_pad("happy"))
        self.assertGreater(state.emotion[0], 0.0)
        self.assertGreater(state.mood[0], 0.0)


class TestVisionNotes(unittest.TestCase):
    def setUp(self):
        self.mem = memory.Memory(":memory:")

    def test_add_and_recent(self):
        self.mem.add_vision_note("ocr", "Alicja w krainie czarów")
        self.mem.add_vision_note("ocr", "2x3=6")
        self.mem.add_vision_note("scene", "coś innego")
        rows = self.mem.recent_vision_notes(limit=10)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["text"], "coś innego")
        ocr = self.mem.recent_vision_notes(limit=10, kinds=("ocr",))
        self.assertEqual(len(ocr), 2)
        self.assertEqual(ocr[0]["text"], "2x3=6")
        self.assertEqual(ocr[0]["kind"], "ocr")

    def test_empty(self):
        self.assertEqual(self.mem.recent_vision_notes(limit=5), [])


class TestEventsAndOcrCommands(unittest.TestCase):
    def test_intents(self):
        cases = {
            "co zauważyłeś": "vision-events",
            "co zauważyłaś": "vision-events",
            "co się działo": "vision-events",
            "co się wydarzyło przed kamerą": "vision-events",
            "jakie zdarzenia z kamery": "vision-events",
            "co słychać u kamery": "vision-events",
            "co widziałaś przed kamerą": "vision-events",
            "co było napisane": "ocr-recent",
            "co przeczytałaś": "ocr-recent",
            "co odczytałaś z kartki": "ocr-recent",
            "ostatni odczyt": "ocr-recent",
        }
        for phrase, route in cases.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_no_false_positives(self):
        for phrase, route in {
            "co się dzieje": "vision-scene",
            "co słychać": "",  # bez „u/z kamery" to zwykłe przywitanie
            "co jest napisane": "camera-ocr",
            "przeczytaj kartkę": "camera-ocr",
        }.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_tools_registered(self):
        for name in ("vision_events", "ocr_recent"):
            self.assertIsNotNone(registry.get(name), name)

    def test_vision_events_tool_empty(self):
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(config, "RUNTIME_DIR", __import__("pathlib").Path(tmp)):
            ctx = ToolContext(settings=config, memory=memory.Memory(":memory:"),
                              registry=registry)
            res = registry.execute("vision_events", {}, ctx)
            self.assertTrue(res.ok)
            self.assertIn("Brak", res.text)

    def test_vision_events_tool_reads_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = __import__("pathlib").Path(tmp)
            with open(runtime / "vision_events.jsonl", "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": 1_700_000_000.0, "kind": "enter",
                                     "text": "Ktoś wszedł do pokoju."},
                                    ensure_ascii=False) + "\n")
            with unittest.mock.patch.object(config, "RUNTIME_DIR", runtime):
                ctx = ToolContext(settings=config, memory=memory.Memory(":memory:"),
                                  registry=registry)
                res = registry.execute("vision_events", {}, ctx)
            self.assertTrue(res.ok)
            self.assertIn("wszedł", res.text)

    def test_ocr_recent_tool(self):
        ctx = ToolContext(settings=config, memory=memory.Memory(":memory:"),
                          registry=registry)
        ctx.memory.add_vision_note("ocr", "KUP MLEKO")
        res = registry.execute("ocr_recent", {}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("KUP MLEKO", res.text)


if __name__ == "__main__":
    unittest.main()