"""Testy kamery sieciowej = „oczy" ASTRO: ONVIF/PTZ (`core.onvif`) + narzędzia (`tools.vision`)."""

import os
import tempfile
import unittest
from unittest import mock

from astro import config
from astro.core import must_have, onvif
from astro.tools import vision


class TestOnvif(unittest.TestCase):
    def test_direction_aliases(self):
        self.assertEqual(onvif.resolve_direction("lewo"), "left")
        self.assertEqual(onvif.resolve_direction("w prawo"), "right")
        self.assertEqual(onvif.resolve_direction("góra"), "up")
        self.assertEqual(onvif.resolve_direction("dół"), "down")
        with self.assertRaises(ValueError):
            onvif.resolve_direction("tam")

    def test_direction_xy_scales(self):
        self.assertEqual(onvif.direction_xy("left", 0.5), (-0.5, 0.0))
        self.assertEqual(onvif.direction_xy("up", 1.0), (0.0, 1.0))
        self.assertEqual(onvif.direction_xy("downright", 1.0), (0.7, -0.7))
        self.assertEqual(onvif.direction_xy("center"), (0.0, 0.0))

    def test_bodies_are_wellformed(self):
        self.assertIn("ContinuousMove", onvif.move_body("profile_0", 0.6, -0.3))
        self.assertIn('x="0.600"', onvif.move_body("profile_0", 0.6, -0.3))
        self.assertIn("GetStatus", onvif.status_body("profile_0"))
        self.assertIn("SetHomePosition", onvif.set_home_body("profile_0"))

    def test_envelope_wsse_only_with_user(self):
        plain = onvif.envelope(onvif.status_body("p"))
        self.assertNotIn("UsernameToken", plain)
        signed = onvif.envelope(onvif.status_body("p"), "admin", "tajne")
        self.assertIn("UsernameToken", signed)
        self.assertIn("PasswordDigest", signed)

    def test_status_parses_position(self):
        reply = ('<env:Envelope><env:Body><tptz:GetStatusResponse><tt:PanTilt x="0.25" '
                 'y="-0.5" space="s"/><tt:MoveStatus><tt:PanTilt>IDLE</tt:PanTilt>'
                 '</tt:MoveStatus></tptz:GetStatusResponse></env:Body></env:Envelope>')
        with mock.patch.object(onvif, "soap", return_value=reply):
            st = onvif.status("http://cam/Ptz", "profile_0")
        self.assertEqual((st["x"], st["y"]), (0.25, -0.5))

    def test_move_detects_fault(self):
        with mock.patch.object(onvif, "soap", return_value="<env:Fault>NotAuthorized</env:Fault>"):
            with self.assertRaises(onvif.OnvifError):
                onvif.move("http://cam/Ptz", "profile_0", 0.1, 0.0)

    def test_nudge_moves_then_stops(self):
        calls = []
        with mock.patch.object(onvif, "move", side_effect=lambda *a, **k: calls.append("move")), \
             mock.patch.object(onvif, "stop", side_effect=lambda *a, **k: calls.append("stop")):
            x, y = onvif.nudge("http://cam/Ptz", "profile_0", "right", ms=10, speed=0.5,
                               sleeper=lambda s: None)
        self.assertEqual((x, y), (0.5, 0.0))
        self.assertEqual(calls, ["move", "stop"])

    def test_nudge_center_only_stops(self):
        calls = []
        with mock.patch.object(onvif, "move", side_effect=lambda *a, **k: calls.append("move")), \
             mock.patch.object(onvif, "stop", side_effect=lambda *a, **k: calls.append("stop")):
            onvif.nudge("http://cam/Ptz", "profile_0", "center", ms=10)
        self.assertEqual(calls, ["stop"])


class TestVisionCamera(unittest.TestCase):
    def _patch(self, **kw):
        base = {"CAMERA_ENABLED": True, "CAMERA_HOST": "192.168.0.1",
                "CAMERA_RTSP": "rtsp://192.168.0.1:554/live/ch0",
                "CAMERA_PTZ_URL": "http://192.168.0.1:8899/onvif/Ptz",
                "CAMERA_PROFILE": "profile_0", "CAMERA_SPEED": 0.6,
                "CAMERA_MOVE_MS": 600, "CAMERA_TIMEOUT": 6.0,
                "CAMERA_SNAPSHOT": "/tmp/astro-cam-test.jpg"}
        base.update(kw)
        return [mock.patch.object(config, k, v) for k, v in base.items()]

    def test_enabled_and_reachable(self):
        patches = self._patch()
        for p in patches:
            p.start()
        try:
            self.assertTrue(vision.network_camera_enabled())
            self.assertTrue(vision.camera_present())
            self.assertNotIn("192.168.0.999", config.CAMERA_RTSP)
        finally:
            for p in patches:
                p.stop()

    def test_disabled_when_flag_off(self):
        with mock.patch.object(config, "CAMERA_ENABLED", False):
            self.assertFalse(vision.network_camera_enabled())

    def test_capture_frame_uses_ffmpeg(self):
        patches = self._patch()
        # CI nie ma ffmpeg w obrazie (2026-10-03) — mockujemy wykrycie, żeby test mierzył
        # logikę capture_frame, a nie dostępność binarki.
        patches.append(mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"))
        for p in patches:
            p.start()
        try:
            path = "/tmp/astro-cam-test.jpg"
            if os.path.exists(path):
                os.remove(path)
            with mock.patch.object(vision.subprocess, "run") as run:
                def fake_run(cmd, **kw):
                    with open(path, "wb") as fh:
                        fh.write(b"jpegdata")
                run.side_effect = fake_run
                out = vision.capture_frame()
            self.assertEqual(out, path)
            self.assertIn("ffmpeg", run.call_args[0][0][0])
            os.remove(path)
        finally:
            for p in patches:
                p.stop()

    def test_ptz_nudge_delegates(self):
        patches = self._patch()
        for p in patches:
            p.start()
        try:
            with mock.patch.object(onvif, "nudge", return_value=(-0.6, 0.0)) as n:
                vision.ptz_nudge("left")
            self.assertEqual(n.call_args[0][2], "left")
        finally:
            for p in patches:
                p.stop()

    def test_flip_filter(self):
        with mock.patch.object(config, "CAMERA_FLIP", "180"):
            self.assertEqual(vision._flip_filter(), "hflip,vflip")
        with mock.patch.object(config, "CAMERA_FLIP", "hflip"):
            self.assertEqual(vision._flip_filter(), "hflip")
        with mock.patch.object(config, "CAMERA_FLIP", "none"):
            self.assertEqual(vision._flip_filter(), "")


class TestCameraToolsAndCommands(unittest.TestCase):
    def test_tools_registered(self):
        from astro.tools import registry as reg
        for name in ("camera_look", "camera_move", "camera_home"):
            self.assertIsNotNone(reg.get(name), name)

    def test_intents(self):
        cases = {
            "co widzisz": "camera-look",
            "spójrz": "camera-look",
            "zrób zdjęcie z kamery": "camera-look",
            "obróć kamerę w lewo": "camera-move",
            "kamera w prawo": "camera-move",
            "popatrz do góry": "camera-move",
            "kamera w dół": "camera-move",
            "stop kamera": "camera-stop",
            "status kamery": "camera-status",
            "czy widzisz": "camera-status",
        }
        for phrase, route in cases.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_handle_move_uses_vision(self):
        with mock.patch.object(vision, "network_camera_enabled", return_value=True), \
             mock.patch.object(vision, "ptz_nudge", return_value=(-0.6, 0.0)) as n:
            reply, route = must_have.handle("obróć kamerę w lewo")
        self.assertEqual(route, "camera-move")
        self.assertIn("lewo", reply)
        self.assertEqual(n.call_args[0][0], "left")

    def test_handle_look_without_camera(self):
        with mock.patch.object(vision, "camera_present", return_value=False):
            reply, route = must_have.handle("co widzisz")
        self.assertEqual(route, "camera-look")
        self.assertIn("kamer", reply.lower())

    def test_handle_status_disabled(self):
        with mock.patch.object(vision, "network_camera_enabled", return_value=False):
            reply, route = must_have.handle("status kamery")
        self.assertEqual(route, "camera-status")
        self.assertIn("wyłączona", reply)


class TestVlmBackend(unittest.TestCase):
    def test_off_when_nothing_configured(self):
        # vlm_ready() = premium-vision (tryb premium+klucze) LUB VLM_MODEL LUB hailo (2026-10-03);
        # w tym teście wyłączamy świadomie wszystkie trzy ścieżki.
        with mock.patch.object(config, "VLM_HAILO", False), \
             mock.patch.object(config, "VLM_MODEL", ""), \
             mock.patch.object(vision, "_premium_vision_ready", return_value=False):
            self.assertEqual(vision.vlm_backend(), "off")
            self.assertFalse(vision.vlm_ready())

    def test_hailo_prefers_npu(self):
        with mock.patch.object(config, "VLM_HAILO", True), \
             mock.patch("astro.backends.npu.NPU_ENGINE.vlm_ready", return_value=True):
            self.assertEqual(vision.vlm_backend(), "hailo")

    def test_hailo_falls_back_to_ollama(self):
        with mock.patch.object(config, "VLM_HAILO", True), \
             mock.patch("astro.backends.npu.NPU_ENGINE.vlm_ready", return_value=False), \
             mock.patch.object(config, "VLM_MODEL", "qwen2.5vl:3b"):
            self.assertEqual(vision.vlm_backend(), "ollama")

    def test_caption_prefers_hailo(self):
        with mock.patch.object(config, "VLM_HAILO", True), \
             mock.patch.object(vision, "_hailo_vlm_ready", return_value=True), \
             mock.patch.object(vision, "_vlm_caption_hailo", return_value="Widzę osobę."):
            self.assertEqual(vision._vlm_caption("/tmp/x.jpg"), "Widzę osobę.")

    def test_looks_polish(self):
        self.assertTrue(vision._looks_polish("Widzę dwie osoby w kuchni."))
        self.assertFalse(vision._looks_polish("The image is unclear, please provide more."))
        self.assertFalse(vision._looks_polish("这是一个测试"))
        looped = "W tle widocz nego, który ma cienki brod. " * 3
        self.assertFalse(vision._looks_polish(looped))

    def test_clean_caption_strips_junk_prefix(self):
        self.assertEqual(vision._clean_caption("!Zobacz: Jest kuchnia."), "Zobacz: Jest kuchnia.")
        self.assertEqual(vision._clean_caption("Assistant: Widzę osobę."), "Widzę osobę.")

    def test_clean_caption_trims_dangling_tail(self):
        out = vision._clean_caption(
            "Widzę 10 osób, a w otoczeniu ważne przedmioty takie jak")
        self.assertFalse(out.endswith("takie jak"))
        self.assertTrue(out.endswith("."))

    def test_clean_caption_keeps_sentence(self):
        self.assertEqual(vision._clean_caption("Widzę dwie osoby przy biurku."),
                         "Widzę dwie osoby przy biurku.")


class TestMultiCamera(unittest.TestCase):
    """Wielokamera (Faza 3): `CAMERA_SOURCES`, wybór kamery, komendy „kamera 2/druga"."""

    def _patch(self, sources="", **kw):
        base = {"CAMERA_ENABLED": True, "CAMERA_HOST": "192.168.0.1",
                "CAMERA_NAME": "kamera",
                "CAMERA_RTSP": "rtsp://192.168.0.1:554/live/ch0",
                "CAMERA_PTZ_URL": "http://192.168.0.1:8899/onvif/Ptz",
                "CAMERA_PROFILE": "profile_0", "CAMERA_SPEED": 0.6,
                "CAMERA_MOVE_MS": 600, "CAMERA_TIMEOUT": 6.0,
                "CAMERA_SNAPSHOT": "/tmp/astro-cam-test.jpg",
                "CAMERA_SOURCES": sources}
        base.update(kw)
        return [mock.patch.object(config, k, v) for k, v in base.items()]

    def test_sources_parsing(self):
        patches = self._patch(
            "ogrod=rtsp://192.168.0.247:554/live/ch0|http://192.168.0.247:8899/onvif/Ptz|p1,"
            "bramka=rtsp://192.168.0.248:554/live/ch0")
        for p in patches:
            p.start()
        try:
            cams = vision.camera_sources()
            self.assertEqual(len(cams), 3)
            self.assertEqual(cams[0]["name"], "kamera")
            self.assertEqual(cams[0]["index"], 0)
            self.assertEqual(cams[1]["name"], "ogrod")
            self.assertEqual(cams[1]["profile"], "p1")
            self.assertEqual(cams[2]["name"], "bramka")
            self.assertEqual(cams[2]["profile"], "profile_0")
            self.assertEqual(vision.camera_count(), 3)
        finally:
            for p in patches:
                p.stop()

    def test_select_by_index_word_name(self):
        patches = self._patch("ogrod=rtsp://192.168.0.247:554/live/ch0")
        for p in patches:
            p.start()
        try:
            self.assertEqual(vision._camera_by_spec("1")["name"], "kamera")
            self.assertEqual(vision._camera_by_spec("2")["name"], "ogrod")
            self.assertEqual(vision._camera_by_spec("druga")["name"], "ogrod")
            self.assertEqual(vision._camera_by_spec("OGROD")["name"], "ogrod")
            with self.assertRaises(ValueError):
                vision._camera_by_spec("5")
            with self.assertRaises(ValueError):
                vision._camera_by_spec("piata")
            with self.assertRaises(ValueError):
                vision._camera_by_spec("nieznana")
        finally:
            for p in patches:
                p.stop()

    def test_capture_frame_uses_selected_source(self):
        patches = self._patch("ogrod=rtsp://192.168.0.247:554/live/ch0")
        # CI nie ma ffmpeg (2026-10-03) — mock wykrycia binarki.
        patches.append(mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"))
        for p in patches:
            p.start()
        try:
            with mock.patch.object(vision.subprocess, "run") as run:
                def fake_run(cmd, **kw):
                    with open(cmd[-1], "wb") as fh:
                        fh.write(b"jpegdata")
                run.side_effect = fake_run
                out = vision.capture_frame(camera="2")
            self.assertTrue(out.endswith("astro-vision-1.jpg"))
            self.assertTrue(any("192.168.0.247" in str(x)
                                for x in run.call_args[0][0]))
        finally:
            for p in patches:
                p.stop()

    def test_ptz_nudge_selected_camera(self):
        patches = self._patch("ogrod=rtsp://192.168.0.247:554/live/ch0|http://cam2:8899/onvif/Ptz")
        for p in patches:
            p.start()
        try:
            cam = vision._camera_by_spec("druga")
            with mock.patch.object(onvif, "nudge", return_value=(0.6, 0.0)) as n:
                vision.ptz_nudge("right", camera=cam)
            self.assertEqual(n.call_args[0][0], "http://cam2:8899/onvif/Ptz")
        finally:
            for p in patches:
                p.stop()

    def test_ptz_missing_for_pure_rtsp(self):
        patches = self._patch("bramka=rtsp://192.168.0.248:554/live/ch0")
        for p in patches:
            p.start()
        try:
            cam = vision._camera_by_spec("2")
            self.assertFalse(cam["ptz"])
        finally:
            for p in patches:
                p.stop()

    def test_intents_with_camera_spec(self):
        cases = {
            "spójrz na kamerę 2": "camera-look",
            "zrób zdjęcie z kamery 3": "camera-look",
            "druga kamera w lewo": "camera-move",
            "kamera trzecia w prawo": "camera-move",
            "kamera 3 na wprost": "camera-home",
            "wyśrodkuj drugą kamerę": "camera-home",
            "przeczytaj na kamerze 2": "camera-ocr",
            "status kamery 2": "camera-status",
            "ile kamer": "camera-status",
            "lista kamer": "camera-status",
            "ile masz kamer": "camera-status",
        }
        for phrase, route in cases.items():
            self.assertEqual(must_have.intent(phrase), route, phrase)

    def test_camera_spec_extraction(self):
        self.assertEqual(must_have._camera_spec("spójrz na kamerę 2"), "2")
        self.assertEqual(must_have._camera_spec("druga kamera w lewo"), "druga")
        self.assertEqual(must_have._camera_spec("kamera 3 na wprost"), "3")
        self.assertIsNone(must_have._camera_spec("co widzisz"))
        self.assertIsNone(must_have._camera_spec("obróć kamerę w lewo"))

    def test_no_false_spec(self):
        for phrase in ("zdjęcie z kamery", "kamera w prawo", "co widzisz"):
            self.assertIsNone(must_have._camera_spec(phrase), phrase)

    def test_camera_status_lists_all(self):
        patches = self._patch("ogrod=rtsp://192.168.0.247:554/live/ch0")
        for p in patches:
            p.start()
        try:
            with mock.patch.object(vision, "camera_reachable", return_value=True):
                text, route = must_have._camera_status(None)
            self.assertEqual(route, "camera-status")
            self.assertIn("2 kamery", text)
            self.assertIn("ogrod", text)
        finally:
            for p in patches:
                p.stop()


class TestImageRgbShapes(unittest.TestCase):
    """Faza 4: `_image_rgb` obsługuje kwadrat (336) i prostokąt (512×288 — Qwen3-VL)."""

    def _img(self, w=2304, h=1296):
        import numpy as np
        return np.zeros((h, w, 3), dtype=np.uint8)

    def test_square(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.jpg")
            cv2.imwrite(path, self._img())
            img = vision._image_rgb(path, 336)
        self.assertEqual(img.shape, (336, 336, 3))

    def test_rect(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.jpg")
            cv2.imwrite(path, self._img())
            img = vision._image_rgb(path, (288, 512))
        self.assertEqual(img.shape, (288, 512, 3))

    def test_zero_size_returns_none(self):
        import cv2
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.jpg")
            cv2.imwrite(path, self._img())
            self.assertIsNone(vision._image_rgb(path, (0, 0)))


if __name__ == "__main__":
    unittest.main()
