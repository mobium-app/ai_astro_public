"""Testy wizji AI: baza twarzy w pamięci, ocena sceny, komendy must-have."""

import unittest
from unittest import mock

from astro import config, memory
from astro.core import must_have
from astro.vision import engine, scene
from astro.tools import registry


def vec(*xs):
    return list(xs)


class TestFaceGallery(unittest.TestCase):
    def setUp(self):
        self.mem = memory.Memory(":memory:")

    def test_add_list_forget(self):
        self.mem.add_face("Anna", vec(1.0, 0.0, 0.0, 0.0))
        self.mem.add_face("Anna", vec(0.9, 0.1, 0.0, 0.0))
        faces = self.mem.list_faces()
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0]["name"], "Anna")
        self.assertEqual(faces[0]["count"], 2)
        self.assertEqual(self.mem.forget_face("Anna"), 1)
        self.assertEqual(self.mem.list_faces(), [])

    def test_match_face_threshold(self):
        self.mem.add_face("Konrad", vec(1.0, 0.0, 0.0, 0.0))
        name, score = self.mem.match_face(vec(0.99, 0.01, 0.0, 0.0), threshold=0.4)
        self.assertEqual(name, "Konrad")
        self.assertGreater(score, 0.9)
        name2, _ = self.mem.match_face(vec(0.0, 1.0, 0.0, 0.0), threshold=0.4)
        self.assertIsNone(name2)

    def test_sightings(self):
        self.mem.add_sighting("Anna", 0.9, known=True)
        self.mem.add_sighting("?", 0.1, known=False)
        rows = self.mem.recent_sightings(5)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "?")


class TestSceneDescribe(unittest.TestCase):
    def test_describe_known_and_objects(self):
        out = {"persons": 1, "known": [{"name": "Anna", "score": 0.9}], "unknown": 0,
               "objects": [{"label": "person", "score": 0.9, "box": []},
                           {"label": "laptop", "score": 0.8, "box": []},
                           {"label": "cup", "score": 0.7, "box": []}],
               "expression": "happy", "brightness": 120}
        text = scene.describe(out)
        self.assertIn("jedną osobę", text)
        self.assertIn("Anna", text)
        self.assertIn("laptop", text)
        self.assertIn("wesoły", text)

    def test_describe_empty(self):
        out = {"persons": 0, "known": [], "unknown": 0, "objects": [],
               "expression": "", "brightness": 20}
        text = scene.describe(out)
        self.assertIn("nikogo", text)
        self.assertIn("ciemno", text)

    def test_who(self):
        self.assertEqual(scene.who({"known": [], "unknown": 0}), "Nie widzę teraz nikogo.")
        self.assertEqual(scene.who({"known": [{"name": "Anna"}], "unknown": 0}),
                         "Widzę: Anna.")
        self.assertIn("nie rozpoznaję", scene.who({"known": [], "unknown": 1}))
        self.assertIn("twarzy", scene.who({"known": [], "unknown": 0, "persons": 1, "faces": 0}))

    def test_assess_uses_memory(self):
        mem = memory.Memory(":memory:")
        mem.add_face("Anna", vec(1.0, 0.0, 0.0, 0.0))
        fake_face = {"box": [10, 10, 50, 50], "score": 0.9, "landmarks": [], "raw": "raw"}
        import numpy as np
        img = np.zeros((64, 64, 3), dtype="uint8")
        with mock.patch.object(engine, "available", return_value=True), \
             mock.patch.object(engine, "detect_faces", return_value=[fake_face]), \
             mock.patch.object(engine, "face_embedding", return_value=vec(1.0, 0.0, 0.0, 0.0)), \
             mock.patch.object(engine, "detect_objects", return_value=[]), \
             mock.patch.object(engine, "expression", return_value="happy"):
            out = scene.assess(img, memory=mem, objects=True, expressions=True)
        self.assertEqual(out["faces"], 1)
        self.assertEqual(out["known"][0]["name"], "Anna")
        self.assertEqual(out["expression"], "happy")


class TestVisionCommands(unittest.TestCase):
    def test_intents(self):
        cases = {
            "oceń otoczenie": "vision-scene",
            "rozejrzyj się": "vision-scene",
            "ile osób": "vision-who",
            "kto jest w pokoju": "vision-who",
            "kogo widzisz": "vision-who",
            "zapamiętaj, to jest Anna": "vision-enroll",
            "zapomnij Anna": "vision-forget",
            "status wizji": "vision-status",
            "kogo znasz": "vision-people",
            "lista osób": "vision-people",
        }
        for phrase, route in cases.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_name_extraction(self):
        self.assertEqual(must_have._vis_name("zapamiętaj, to jest Anna", r"\b(?:zapamietaj|zapisz)"),
                         "anna")
        self.assertEqual(must_have._vis_name("zapisz Konrad", r"\b(?:zapamietaj|zapisz)"), "konrad")
        self.assertEqual(must_have._vis_name("zapomnij o Annie", r"\bzapomnij"), "annie")

    def test_tools_registered(self):
        for name in ("camera_scene", "camera_people", "person_enroll", "person_forget",
                     "person_list", "vision_status", "camera_move", "camera_home",
                     "camera_look"):
            self.assertIsNotNone(registry.get(name), name)


class TestMultiFaceEnroll(unittest.TestCase):
    def _ctx(self, mem):
        from astro.tools import ToolContext
        return ToolContext(settings=config, memory=mem, registry=registry)

    def test_enroll_picks_unknown_face(self):
        import numpy as np
        from astro.tools import vision
        mem = memory.Memory(":memory:")
        mem.add_face("Ja", vec(1.0, 0.0, 0.0, 0.0))
        face_a = {"box": [0, 0, 120, 120], "score": 0.95, "landmarks": [], "raw": "A"}
        face_b = {"box": [150, 150, 40, 40], "score": 0.80, "landmarks": [], "raw": "B"}

        def fake_emb(img, f):
            return vec(1.0, 0.0, 0.0, 0.0) if f["raw"] == "A" else vec(0.0, 1.0, 0.0, 0.0)

        img = np.zeros((200, 200, 3), dtype="uint8")
        with mock.patch.object(vision, "capture_frame", return_value="/tmp/f.jpg"), \
             mock.patch.object(vision, "_load_bgr", return_value=img), \
             mock.patch.object(engine, "available", return_value=True), \
             mock.patch.object(engine, "detect_faces", return_value=[face_a, face_b]), \
             mock.patch.object(engine, "face_embedding", side_effect=fake_emb):
            res = registry.execute("person_enroll", {"name": "Żona"}, self._ctx(mem))
        self.assertTrue(res.ok, res.text)
        names = {f["name"] for f in mem.list_faces()}
        self.assertEqual(names, {"Ja", "Żona"})
        # mała nieznana twarz (B) została zapisana jako Żona, a nie duża znana (A)
        emb = mem.con.execute("SELECT embedding FROM faces WHERE name='Żona'").fetchone()[0]
        from astro.memory.store import _unpack_emb
        self.assertEqual(_unpack_emb(emb), vec(0.0, 1.0, 0.0, 0.0))

    def test_person_list(self):
        from astro.tools import ToolContext
        mem = memory.Memory(":memory:")
        mem.add_face("Anna", vec(1.0, 0.0, 0.0, 0.0))
        mem.add_face("Konrad", vec(0.0, 1.0, 0.0, 0.0))
        ctx = ToolContext(settings=config, memory=mem, registry=registry)
        res = registry.execute("person_list", {}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("Anna", res.text)
        self.assertIn("Konrad", res.text)

    def test_person_list_empty(self):
        from astro.tools import ToolContext
        ctx = ToolContext(settings=config, memory=memory.Memory(":memory:"), registry=registry)
        res = registry.execute("person_list", {}, ctx)
        self.assertIn("nikogo", res.text.lower())


class TestWatchEvents(unittest.TestCase):
    def test_plan_emits_on_first_sight(self):
        from astro.scripts import vision_watch as vw
        state = {"last_unknown": 0.0, "last_name": {}}
        events, state = vw.plan_events(state, known=["Anna"], unknown=1, now=10000,
                                       unknown_cd=300, known_cd=1800)
        kinds = [k for k, _ in events]
        self.assertIn("alert", kinds)
        self.assertIn("return", kinds)
        # druga tura zaraz po — brak zdarzeń (cooldowny)
        events2, _ = vw.plan_events(state, known=["Anna"], unknown=1, now=10001,
                                    unknown_cd=300, known_cd=1800)
        self.assertEqual(events2, [])

    def test_plan_no_unknown(self):
        from astro.scripts import vision_watch as vw
        events, _ = vw.plan_events({"last_unknown": 0.0, "last_name": {}}, known=[], unknown=0,
                                   now=1000)
        self.assertEqual(events, [])

    def test_plan_after_cooldown(self):
        from astro.scripts import vision_watch as vw
        state = {"last_unknown": 0.0, "last_name": {"Anna": 0.0}}
        events, _ = vw.plan_events(state, known=["Anna"], unknown=0, now=10000,
                                   known_cd=1800)
        self.assertEqual([k for k, _ in events], ["return"])

    def test_initiative_event_respects_cooldown(self):
        import os
        import tempfile
        from astro.core.initiative import Initiative
        path = os.path.join(tempfile.mkdtemp(), "init.json")
        init = Initiative(state_path=path, enabled=True)
        init._state["last_spoke"] = 0.0
        with mock.patch.object(config, "INITIATIVE_QUIET_START", 0), \
             mock.patch.object(config, "INITIATIVE_QUIET_END", 0):
            first = init.event("Uwaga, ktoś jest.", kind="alert", now=1000)
            second = init.event("Znowu ktoś.", kind="alert", now=1001)
        self.assertEqual(first, "Uwaga, ktoś jest.")
        self.assertIsNone(second)


class TestVlm(unittest.TestCase):
    def test_vlm_caption_disabled_without_model(self):
        import os
        from astro.tools import vision
        with mock.patch.object(config, "VLM_MODEL", ""):
            self.assertEqual(vision._vlm_caption("/nie/ma.jpg"), "")
        self.assertTrue(os.path.abspath(vision.__file__))

    def test_image_b64_fallback_raw(self):
        import base64
        import os
        import tempfile
        from astro.tools import vision
        p = os.path.join(tempfile.mkdtemp(), "x.bin")
        with open(p, "wb") as fh:
            fh.write(b"hello")
        self.assertEqual(base64.b64decode(vision._image_b64(p)), b"hello")


class TestBodyReID(unittest.TestCase):
    def setUp(self):
        self.mem = memory.Memory(":memory:")

    def test_add_list_match_body(self):
        self.mem.add_body("Konrad", vec(1.0, 0.0, 0.0, 0.0))
        self.assertEqual(self.mem.list_bodies()[0]["name"], "Konrad")
        name, score = self.mem.match_body(vec(0.98, 0.02, 0.0, 0.0), threshold=0.55)
        self.assertEqual(name, "Konrad")
        self.assertGreater(score, 0.9)
        name2, _ = self.mem.match_body(vec(0.0, 1.0, 0.0, 0.0), threshold=0.55)
        self.assertIsNone(name2)

    def test_forget_person_removes_both(self):
        self.mem.add_face("Anna", vec(1.0, 0.0, 0.0, 0.0))
        self.mem.add_body("Anna", vec(0.0, 1.0, 0.0, 0.0))
        self.assertEqual(self.mem.forget_person("Anna"), 2)
        self.assertEqual(self.mem.list_faces(), [])
        self.assertEqual(self.mem.list_bodies(), [])

    def test_scene_uses_body_when_no_face(self):
        import numpy as np
        mem = memory.Memory(":memory:")
        mem.add_body("Żona", vec(1.0, 0.0, 0.0, 0.0))
        img = np.zeros((200, 200, 3), dtype="uint8")
        with mock.patch.object(engine, "available", return_value=True), \
             mock.patch.object(engine, "detect_objects",
                               return_value=[{"label": "person", "score": 0.9,
                                              "box": [10, 10, 120, 180]}]), \
             mock.patch.object(engine, "detect_faces", return_value=[]), \
             mock.patch.object(engine, "person_embedding", return_value=vec(1.0, 0.0, 0.0, 0.0)):
            out = scene.assess(img, memory=mem, objects=True, faces=True)
        self.assertEqual(out["body_known"][0]["name"], "Żona")
        self.assertIn("Żona", scene.who(out))

    def test_overlap(self):
        from astro.tools import vision
        self.assertGreater(vision._overlap([10, 10, 20, 20], [0, 0, 100, 100]), 0)
        self.assertEqual(vision._overlap([200, 200, 10, 10], [0, 0, 100, 100]), 0)


class TestNameNormalization(unittest.TestCase):
    def test_normalize_name(self):
        from astro.memory.store import normalize_name
        self.assertEqual(normalize_name("kasia"), "Kasia")
        self.assertEqual(normalize_name("  michal "), "Michal")
        self.assertEqual(normalize_name("Anna"), "Anna")
        self.assertEqual(normalize_name(""), "")

    def test_same_person_case_insensitive(self):
        mem = memory.Memory(":memory:")
        mem.add_face("kasia", vec(1.0, 0.0, 0.0, 0.0))
        mem.add_face("Kasia", vec(0.9, 0.1, 0.0, 0.0))
        mem.add_body("kasia", vec(0.0, 1.0, 0.0, 0.0))
        self.assertEqual(len(mem.list_faces()), 1)
        self.assertEqual(mem.list_faces()[0]["name"], "Kasia")
        self.assertEqual(mem.list_faces()[0]["count"], 2)
        self.assertEqual(len(mem.list_bodies()), 1)


class TestSightings(unittest.TestCase):
    def test_summary_and_tool(self):
        from astro.tools import ToolContext
        mem = memory.Memory(":memory:")
        mem.add_sighting("Kasia", 0.9, known=True)
        mem.add_sighting("Kasia", 0.8, known=True)
        mem.add_sighting("Michał", 0.7, known=True)
        mem.add_sighting("?", 0.1, known=False)  # nieznana — pomijana
        summary = mem.sightings_summary(day_start=0)
        names = {s["name"]: s["count"] for s in summary}
        self.assertEqual(names.get("Kasia"), 2)
        self.assertEqual(names.get("Michał"), 1)
        self.assertNotIn("?", names)
        ctx = ToolContext(settings=config, memory=mem, registry=registry)
        res = registry.execute("person_sightings", {"period": "today"}, ctx)
        self.assertTrue(res.ok)
        self.assertIn("Kasia", res.text)

    def test_intents(self):
        for phrase, route in {
            "kto był dzisiaj": "vision-seen",
            "kto tu był": "vision-seen",
            "kto się pojawił": "vision-seen",
            "kiedy ostatnio widział Kasię": "vision-seen",
        }.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_sightings_since(self):
        import time as _t
        mem = memory.Memory(":memory:")
        mem.add_sighting("Anna", 0.9, known=True)
        rows = mem.sightings_since(_t.time() - 60)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Anna")
        self.assertEqual(mem.sightings_since(_t.time() + 100), [])


if __name__ == "__main__":
    unittest.main()
