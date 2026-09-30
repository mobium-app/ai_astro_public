"""Testy API wizji (`scripts/vision_api.py`): galeria, enroll, obrót, opis z info."""

import unittest
from unittest import mock

try:
    from astro.scripts import vision_api
    HAS_FLASK = True
except Exception:  # runner bez Flask (API wizji chodzi w venv)
    vision_api = None
    HAS_FLASK = False


class FakeMemory:
    def __init__(self, faces=None):
        self._faces = faces or []

    def list_faces(self):
        return self._faces

    def list_bodies(self):
        return []

    def forget_face(self, name):
        before = len(self._faces)
        self._faces = [f for f in self._faces if f["name"] != name]
        return before - len(self._faces)


@unittest.skipUnless(HAS_FLASK, "Flask niedostępny (API wizji chodzi w venv)")
class TestAssessFromInfo(unittest.TestCase):
    def test_known_and_unknown(self):
        info = {"faces": [{"name": "Anna", "match": 0.8}, {"name": None, "match": 0.0}],
                "objects": [{"label": "person", "score": 0.9, "box": []}],
                "persons": 2, "expression": "happy"}
        out = vision_api._assess_from_info(info, 120)
        self.assertEqual(out["known"][0]["name"], "Anna")
        self.assertEqual(out["unknown"], 1)
        self.assertEqual(out["persons"], 2)


@unittest.skipUnless(HAS_FLASK, "Flask niedostępny (API wizji chodzi w venv)")
class TestEndpoints(unittest.TestCase):
    def setUp(self):
        vision_api.app.config["TESTING"] = True
        self.client = vision_api.app.test_client()

    def test_flip_toggle(self):
        vision_api._FLIP["mode"] = "180"
        r = self.client.get("/flip?toggle=1")
        self.assertEqual(r.get_json()["flip"], "none")
        r = self.client.get("/flip?toggle=1")
        self.assertEqual(r.get_json()["flip"], "180")
        self.client.get("/flip?mode=180")

    def test_faces(self):
        with mock.patch.object(vision_api, "memory",
                               return_value=FakeMemory([{"name": "Anna", "count": 1}])):
            r = self.client.get("/faces")
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(r.get_json()["faces"][0]["name"], "Anna")

    def test_forget(self):
        with mock.patch.object(vision_api, "memory",
                               return_value=FakeMemory([{"name": "Anna", "count": 1}])):
            r = self.client.post("/forget", data={"name": "Anna"})
        self.assertTrue(r.get_json()["ok"])

    def test_enroll_requires_name(self):
        r = self.client.get("/enroll")
        self.assertEqual(r.status_code, 400)

    def test_enroll_calls_tool(self):
        class Res:
            ok = True
            text = "Zapamiętałem twarz: Anna."
        with mock.patch.object(vision_api.registry, "execute", return_value=Res()) as ex:
            r = self.client.post("/enroll", data={"name": "Anna"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(ex.call_args[0][0], "person_enroll")

    def test_caption(self):
        import numpy as np
        img = np.zeros((10, 10, 3), dtype="uint8")
        with mock.patch.object(vision_api, "_frames", return_value=iter([img])), \
             mock.patch.object(vision_api.vision, "_vlm_caption", return_value="Opis sceny."):
            r = self.client.get("/caption")
        self.assertEqual(r.get_json()["caption"], "Opis sceny.")


if __name__ == "__main__":
    unittest.main()
