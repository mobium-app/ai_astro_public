"""Testy OCR (vision/ocr.py) i prywatności wizji (vision/privacy.py) — Faza 5/6."""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from astro import config
from astro.vision import ocr, privacy


class TestOcr(unittest.TestCase):
    def test_available_matches_binary(self):
        with mock.patch("astro.vision.ocr.shutil.which", return_value="/usr/bin/tesseract"):
            self.assertTrue(ocr.available())
        with mock.patch("astro.vision.ocr.shutil.which", return_value=None):
            with mock.patch.object(config, "TESSERACT_BIN", ""):
                self.assertFalse(ocr.available())

    def test_read_missing_file_empty(self):
        self.assertEqual(ocr.read_text("/nie/ma/pliku.png"), "")

    def test_read_real_image(self):
        if not ocr.available():
            self.skipTest("brak tesseract")
        import cv2
        img = np.full((200, 700, 3), 255, np.uint8)
        cv2.putText(img, "Przeczytaj ten tekst", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                    (0, 0, 0), 3)
        p = os.path.join(tempfile.mkdtemp(), "t.png")
        cv2.imwrite(p, img)
        self.assertIn("Przeczytaj", ocr.read_text(p))

    def test_clean_merges_short_lines(self):
        self.assertEqual(ocr._clean("Ala\nma\nkota.\n"), "Ala ma kota.")


class TestPrivacy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._p1 = mock.patch.object(config, "RUNTIME_DIR", self._tmp)
        self._p2 = mock.patch.object(config, "LOGS_DIR", self._tmp)
        self._p1.start()
        self._p2.start()
        self.addCleanup(self._p1.stop)
        self.addCleanup(self._p2.stop)

    def test_watch_off_toggle(self):
        self.assertFalse(privacy.watch_off())
        self.assertTrue(privacy.set_watch_off(True))
        self.assertTrue(privacy.watch_off())
        self.assertFalse(privacy.set_watch_off(False))
        self.assertFalse(privacy.watch_off())

    def test_audit_writes_and_tails(self):
        privacy.audit("enroll", target="Anna", note="twarz")
        privacy.audit("forget", target="Anna")
        rows = privacy.audit_tail(10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["action"], "forget")  # najnowsze pierwsze
        self.assertEqual(rows[1]["target"], "Anna")

    def test_status_line(self):
        line = privacy.status_line()
        self.assertIn("nasłuch", line)


if __name__ == "__main__":
    unittest.main()
