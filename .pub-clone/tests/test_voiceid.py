"""Testy identyfikacji mówcy (D1): enroll/identify, prób, trwałość, centroid."""

import os
import tempfile
import unittest

from astro.user.voiceid import VoiceID


class TestVoiceID(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "voiceid.json")

    def test_enroll_and_identify(self):
        vid = VoiceID(path=self.path, threshold=0.9)
        vid.enroll("Anna", [1, 0, 0])
        vid.enroll("Piotr", [0, 1, 0])
        self.assertEqual(vid.identify([0.98, 0.02, 0])[0], "Anna")
        self.assertEqual(vid.identify([0.0, 1.0, 0])[0], "Piotr")

    def test_unknown_below_threshold(self):
        vid = VoiceID(path=self.path, threshold=0.95)
        vid.enroll("Anna", [1, 0, 0])
        self.assertEqual(vid.identify([0, 0, 1])[0], "")

    def test_centroid_average(self):
        vid = VoiceID(path=self.path)
        vid.enroll("A", [1.0, 0.0])
        vid.enroll("A", [0.0, 1.0])
        c = vid.profiles["A"]["centroid"]
        self.assertAlmostEqual(c[0], 0.5)
        self.assertAlmostEqual(c[1], 0.5)
        self.assertEqual(vid.profiles["A"]["count"], 2)

    def test_persistence_roundtrip(self):
        VoiceID(path=self.path).enroll("Anna", [1, 0, 0])
        again = VoiceID(path=self.path)
        self.assertEqual(again.profiles["Anna"]["count"], 1)

    def test_forget(self):
        vid = VoiceID(path=self.path)
        vid.enroll("Anna", [1, 0, 0])
        self.assertTrue(vid.forget("Anna"))
        self.assertFalse(vid.forget("Anna"))

    def test_empty_vector_safe(self):
        vid = VoiceID(path=self.path)
        self.assertEqual(vid.identify([])[0], "")
        self.assertFalse(vid.enroll("", [1, 0]))


if __name__ == "__main__":
    unittest.main()
