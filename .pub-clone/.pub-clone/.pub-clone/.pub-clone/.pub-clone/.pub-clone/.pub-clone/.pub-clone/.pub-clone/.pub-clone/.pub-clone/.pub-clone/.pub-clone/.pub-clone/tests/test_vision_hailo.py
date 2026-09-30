"""Testy detekcji obiektów na Hailo NPU (vision/hailo.py) — bez urządzenia (mocki/dekodowanie)."""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from astro import config
from astro.vision import engine, hailo


class TestDecode(unittest.TestCase):
    def _detections(self, rows):
        """80 klas NMS-by-class; rows = {(class_id, row)}."""
        dets = [np.zeros((0, 5), dtype=np.float64) for _ in range(80)]
        for cid, row in rows:
            dets[cid] = np.array([row], dtype=np.float64)
        return dets

    def test_wide_image_padding_correction(self):
        # w=1000, h=500 -> size=1000, pad=250 (padding pionowy).
        rows = [(0, [0.3, 0.2, 0.5, 0.5, 0.9])]
        out = hailo.HailoDetector._decode(self._detections(rows), 500, 1000, 0.45)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "person")
        self.assertAlmostEqual(out[0]["score"], 0.9)
        self.assertEqual([round(v) for v in out[0]["box"]], [200, 50, 500, 250])

    def test_tall_image_padding_correction(self):
        # h=800, w=400 -> size=800, pad=200 (padding poziomy).
        rows = [(0, [0.1, 0.3, 0.4, 0.6, 0.8])]
        out = hailo.HailoDetector._decode(self._detections(rows), 800, 400, 0.45)
        self.assertEqual([round(v) for v in out[0]["box"]], [40, 80, 280, 320])

    def test_square_no_padding(self):
        rows = [(5, [0.1, 0.2, 0.4, 0.5, 0.7])]  # class 5 = bus
        out = hailo.HailoDetector._decode(self._detections(rows), 640, 640, 0.45)
        self.assertEqual(out[0]["label"], "bus")
        self.assertEqual([round(v) for v in out[0]["box"]], [128, 64, 320, 256])

    def test_threshold_filters_and_sorts(self):
        rows = [(0, [0.1, 0.1, 0.2, 0.2, 0.40]),   # poniżej progu
                (2, [0.3, 0.3, 0.4, 0.4, 0.60]),   # car
                (0, [0.5, 0.5, 0.6, 0.6, 0.95])]   # person (najwyższy)
        out = hailo.HailoDetector._decode(self._detections(rows), 640, 640, 0.45)
        self.assertEqual([(o["label"], round(o["score"], 2)) for o in out],
                         [("person", 0.95), ("car", 0.6)])


class TestPreprocess(unittest.TestCase):
    def test_shape_and_border(self):
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        out = hailo.HailoDetector._preprocess(img, (640, 640, 3))
        self.assertEqual(out.shape, (640, 640, 3))
        # Górny wiersz to padding (szary 114) — obraz był szerszy niż wyższy.
        self.assertTrue(np.all(out[0, :, :] == 114))

    def test_square(self):
        img = np.zeros((640, 640, 3), dtype=np.uint8)
        out = hailo.HailoDetector._preprocess(img, (640, 640, 3))
        self.assertEqual(out.shape, (640, 640, 3))


class TestPathsAndAvailability(unittest.TestCase):
    def test_available_false_without_hef(self):
        det = hailo.HailoDetector(hef="/nonexistent/yolo.hef")
        self.assertFalse(det.available())

    def test_hef_path_from_config(self):
        with tempfile.NamedTemporaryFile(suffix=".hef") as fh:
            old = getattr(config, "VISION_HEF", "")
            config.VISION_HEF = fh.name
            try:
                self.assertEqual(hailo.hef_path(), fh.name)
            finally:
                config.VISION_HEF = old

    def test_hef_path_default_repo(self):
        old = getattr(config, "VISION_HEF", "")
        old_dir = getattr(config, "VISION_HAILO_DIR", None)
        config.VISION_HEF = ""
        with tempfile.TemporaryDirectory() as tmp:
            config.VISION_HAILO_DIR = tmp
            dummy = os.path.join(tmp, config.VISION_OBJECT_HEF)
            with open(dummy, "wb") as fh:
                fh.write(b"dummy")
            try:
                self.assertEqual(hailo.hef_path(), dummy)
            finally:
                config.VISION_HEF = old
                config.VISION_HAILO_DIR = old_dir


class TestEngineIntegration(unittest.TestCase):
    def test_fallback_to_cpu_on_npu_error(self):
        class BadDetector:
            def available(self):
                return True

            def detect_objects(self, image, prob=None):
                raise RuntimeError("NPU busy")

        with mock.patch.object(engine, "_npu_detector", return_value=BadDetector()), \
             mock.patch.object(engine, "_detect_objects_cpu", return_value=["cpu"]) as cpu:
            self.assertEqual(engine.detect_objects(np.zeros((10, 10, 3), np.uint8)), ["cpu"])
            cpu.assert_called_once()

    def test_uses_npu_when_ok(self):
        class OkDetector:
            def available(self):
                return True

            def detect_objects(self, image, prob=None):
                return ["npu"]

        with mock.patch.object(engine, "_npu_detector", return_value=OkDetector()), \
             mock.patch.object(engine, "_detect_objects_cpu", side_effect=AssertionError("nie CPU")):
            self.assertEqual(engine.detect_objects(np.zeros((10, 10, 3), np.uint8)), ["npu"])

    def test_get_detector_disabled(self):
        old = config.VISION_NPU
        config.VISION_NPU = False
        try:
            self.assertIsNone(hailo.get_detector())
        finally:
            config.VISION_NPU = old


class TestFaceDecode(unittest.TestCase):
    @staticmethod
    def _res(fm, score_at=None, box_at=None, kps_at=None):
        """Syntetyczne wyjścia SCRFD: 2 kotwice/krok 8/16/32 (tu fm=2 → stride 320)."""
        res = {"s": np.zeros((fm, fm, 2), dtype=np.float32),
               "b": np.zeros((fm, fm, 8), dtype=np.float32),
               "k": np.zeros((fm, fm, 20), dtype=np.float32)}
        if score_at:
            y, x, a, v = score_at
            res["s"][y, x, a] = v
        if box_at:
            y, x, a, vals = box_at
            res["b"][y, x, a * 4:a * 4 + 4] = vals
        if kps_at:
            y, x, a, vals = kps_at
            res["k"][y, x, a * 10:a * 10 + 10] = vals
        return res

    def test_single_anchor_decode(self):
        # kotwica (y=0,x=0,a=0): center=(0,0), d=(1,1,1,1) → box = ±320.
        res = self._res(2, score_at=(0, 0, 0, 0.9), box_at=(0, 0, 0, [1, 1, 1, 1]),
                        kps_at=(0, 0, 0, [0.1] * 10))
        boxes, scores, lm = hailo.HailoFaceDetector._decode(res, 0.5, 0.4)
        self.assertEqual(len(boxes), 1)
        self.assertAlmostEqual(scores[0], 0.9)
        self.assertEqual([round(v) for v in boxes[0]], [-320, -320, 320, 320])
        # landmark 0 = center + k*stride = (32, 32)
        self.assertEqual([round(v) for v in lm[0][0]], [32, 32])

    def test_threshold_filters(self):
        res = self._res(2, score_at=(0, 0, 1, 0.3), box_at=(0, 0, 1, [1, 1, 1, 1]))
        boxes, scores, lm = hailo.HailoFaceDetector._decode(res, 0.5, 0.4)
        self.assertEqual(boxes, [])

    def test_nms_suppresses_overlaps(self):
        boxes = [[0, 0, 100, 100], [10, 10, 110, 110], [500, 500, 600, 600]]
        scores = [0.9, 0.8, 0.7]
        keep = hailo.HailoFaceDetector._nms(boxes, scores, 0.4)
        self.assertEqual(keep, [0, 2])

    def test_nms_empty(self):
        self.assertEqual(hailo.HailoFaceDetector._nms([], [], 0.4), [])


class TestFacePathsAndAvailability(unittest.TestCase):
    def test_available_false_without_hef(self):
        det = hailo.HailoFaceDetector(hef="/nonexistent/scrfd.hef")
        self.assertFalse(det.available())

    def test_face_hef_path_default_repo(self):
        old = getattr(config, "VISION_FACE_HEF", "")
        old_dir = getattr(config, "VISION_HAILO_DIR", None)
        config.VISION_FACE_HEF = "scrfd_2.5g.hef"
        with tempfile.TemporaryDirectory() as tmp:
            config.VISION_HAILO_DIR = tmp
            dummy = os.path.join(tmp, "scrfd_2.5g.hef")
            with open(dummy, "wb") as fh:
                fh.write(b"dummy")
            try:
                self.assertEqual(hailo.face_hef_path(), dummy)
            finally:
                config.VISION_FACE_HEF = old
                config.VISION_HAILO_DIR = old_dir

    def test_get_face_detector_gated(self):
        old = config.VISION_NPU
        config.VISION_NPU = False
        try:
            self.assertIsNone(hailo.get_face_detector())
        finally:
            config.VISION_NPU = old


class TestAlignLandmarks(unittest.TestCase):
    def test_align_returns_112(self):
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        lm = [80, 70, 120, 70, 100, 95, 85, 120, 115, 120]
        aligned = engine._align_landmarks(img, lm)
        self.assertIsNotNone(aligned)
        self.assertEqual(aligned.shape, (112, 112, 3))

    def test_align_missing_landmarks(self):
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        self.assertIsNone(engine._align_landmarks(img, [1, 2, 3]))


class TestEngineFaceIntegration(unittest.TestCase):
    def test_fallback_to_cpu_on_npu_error(self):
        class BadDetector:
            def available(self):
                return True

            def detect_faces(self, image, score=None):
                raise RuntimeError("NPU busy")

        with mock.patch.object(engine, "_npu_face_detector", return_value=BadDetector()), \
             mock.patch.object(engine, "_detect_faces_cpu", return_value=["cpu"]) as cpu:
            self.assertEqual(engine.detect_faces(np.zeros((10, 10, 3), np.uint8)), ["cpu"])
            cpu.assert_called_once()

    def test_uses_npu_when_ok(self):
        class OkDetector:
            def available(self):
                return True

            def detect_faces(self, image, score=None):
                return ["npu"]

        with mock.patch.object(engine, "_npu_face_detector", return_value=OkDetector()), \
             mock.patch.object(engine, "_detect_faces_cpu", side_effect=AssertionError("nie CPU")):
            self.assertEqual(engine.detect_faces(np.zeros((10, 10, 3), np.uint8)), ["npu"])


if __name__ == "__main__":
    unittest.main()
