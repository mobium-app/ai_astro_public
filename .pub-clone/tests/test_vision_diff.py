"""Testy monitora zmian kadru (vision/diff.py) — Faza 2 „oczy": ruch, wejście/wyjście, obiekty."""

import unittest

import numpy as np

from astro.vision import diff


class TestFingerprintDiff(unittest.TestCase):
    def _img(self, val):
        return np.full((120, 160, 3), val, dtype=np.uint8)

    def test_same_frame_no_change(self):
        a = diff._fingerprint(self._img(60))
        m = diff.diff_frame(a, diff._fingerprint(self._img(60)))
        self.assertFalse(m["motion"])
        self.assertFalse(m["scene_change"])
        self.assertAlmostEqual(m["mean_abs"], 0.0)

    def test_big_change_detected(self):
        a = diff._fingerprint(self._img(30))
        m = diff.diff_frame(a, diff._fingerprint(self._img(220)))
        self.assertTrue(m["motion"])
        self.assertTrue(m["scene_change"])

    def test_first_frame_no_events(self):
        m = diff.diff_frame(None, diff._fingerprint(self._img(100)))
        self.assertFalse(m["motion"])
        self.assertFalse(m["scene_change"])

    def test_fingerprint_roundtrip(self):
        fp = diff._fingerprint(self._img(90))
        st = diff.state_from_fingerprint(fp)
        back = diff.fingerprint_from_state(st)
        self.assertIsNotNone(back)
        self.assertEqual(back[0].shape, (64, 64))


class TestPlanChangeEvents(unittest.TestCase):
    def test_enter(self):
        texts, _cd = diff.plan_change_events(set(), set(), False, True, False, False, {}, 1000.0)
        self.assertEqual(texts[0][0], "enter")

    def test_leave(self):
        texts, _cd = diff.plan_change_events(set(), set(), True, False, False, False, {}, 1000.0)
        self.assertEqual(texts[0][0], "leave")

    def test_appeared_object(self):
        texts, _cd = diff.plan_change_events({"chair"}, {"chair", "cup"}, True, True,
                                             False, False, {}, 1000.0)
        self.assertTrue(any(k == "appeared" for k, _ in texts))

    def test_disappeared_object(self):
        texts, _cd = diff.plan_change_events({"chair", "cup"}, {"chair"}, True, True,
                                             False, False, {}, 1000.0)
        self.assertTrue(any(k == "disappeared" for k, _ in texts))

    def test_person_not_reported_as_object(self):
        # „person" obsługują twarze/wejście — nie dublujemy jako „appeared".
        texts, _cd = diff.plan_change_events({"chair"}, {"chair", "person"}, True, True,
                                             False, False, {}, 1000.0)
        self.assertFalse(any(k == "appeared" for k, _ in texts))

    def test_cooldown_blocks_repeat(self):
        texts, cd = diff.plan_change_events(set(), set(), False, True, False, False, {}, 1000.0)
        self.assertEqual(texts[0][0], "enter")
        texts2, _ = diff.plan_change_events(set(), set(), False, True, False, False, cd, 1010.0)
        self.assertEqual(texts2, [])

    def test_cooldown_expires(self):
        _t, cd = diff.plan_change_events(set(), set(), False, True, False, False, {}, 1000.0)
        texts, _ = diff.plan_change_events(set(), set(), False, True, False, False, cd, 1200.0,
                                           cd_enter=60.0)
        self.assertEqual(texts[0][0], "enter")

    def test_scene_change_priority_over_motion(self):
        texts, _cd = diff.plan_change_events(set(), set(), True, True, True, True, {}, 1000.0)
        kinds = [k for k, _ in texts]
        self.assertIn("scene_change", kinds)
        self.assertNotIn("motion", kinds)  # scene_change wygrywa (elif)

    def test_motion_when_no_scene_change(self):
        texts, _cd = diff.plan_change_events(set(), set(), True, True, True, False, {}, 1000.0)
        self.assertTrue(any(k == "motion" for k, _ in texts))


if __name__ == "__main__":
    unittest.main()
