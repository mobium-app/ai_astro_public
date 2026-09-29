"""Detekcja na Hailo NPU (Hailo-10H) — obiekty (YOLOv8) i twarze (SCRFD) — odciążenie CPU.

Motywacja (2026-09-29): detekcja na CPU (OpenCV/ONNX NanoDet/YuNet) zajmuje dziesiątki–setki ms
i obciąża rdzenie potrzebne do mowy/agenta. Hailo-10H liczy YOLOv8/SCRFD w ~15–25 ms, zwalniając CPU.

Współdzielony VDevice: Hailo-10H daje urządzenie na wyłączność procesowi. Oba detektory używają
**tego samego VDevice co STT/VLM** (`backends.npu.NpuEngine.get_vdevice()`), więc `astro.service` ma
jedną instancję i nie ma konfliktu. Jeśli VDevice nie da się otworzyć (np. inny proces trzyma NPU),
`available()`/`detect_*` zgłaszają wyjątek, a `vision.engine` robi fallback na CPU.

Formaty wyjść HEF:
  * YOLOv8 (obiekty): NMS na urządzeniu (`FormatOrder.HAILO_NMS_BY_CLASS`) — `get_buffer()` zwraca
    listę 80 tablic `(N,5)` `[ymin,xmin,ymax,xmax,score]` (znormalizowane do listboxa 640×640);
    dekodowanie 1:1 z hailo-apps (`denormalize_and_rm_pad`).
  * SCRFD (twarze): wyjścia surowe (bez NMS) — 3 skale × (scores 2, boxy 8, landmarki 20) na komórkę;
    ustawiamy typ wyjść na FLOAT32 (dequantyzacja na urządzeniu) i dekodujemy jak hailo-apps
    `scrfd.cpp` (kotwice 2/krok 8/16/32, `box = center ± d*stride`, landmarki `center + k*stride`,
    score = kanał kotwicy) + NMS (IoU 0,4).
"""

from __future__ import annotations

import os
import threading
import time

from .. import config
from ..backends.npu import NPU_TELEMETRY, hailo_platform_available

_LOCK = threading.Lock()
_LOCAL_LOCK = threading.Lock()
_DETECTOR = None
_FACE_DETECTOR = None


def hef_path():
    """Ścieżka do HEF detekcji obiektów: env/repo > `models/hailo/<VISION_OBJECT_HEF>`."""
    env = os.environ.get("ASTRO_VISION_HEF", "") or getattr(config, "VISION_HEF", "")
    if env and os.path.exists(env):
        return env
    d = getattr(config, "VISION_HAILO_DIR", None)
    name = getattr(config, "VISION_OBJECT_HEF", "yolov8s.hef")
    if d:
        p = os.path.join(str(d), name)
        if os.path.exists(p):
            return p
    return ""


def face_hef_path():
    """Ścieżka do HEF detekcji twarzy: env/repo > `models/hailo/<VISION_FACE_HEF>`."""
    env = os.environ.get("ASTRO_VISION_FACE_HEF_PATH", "")
    if env and os.path.exists(env):
        return env
    name = getattr(config, "VISION_FACE_HEF", "scrfd_2.5g.hef")
    if os.path.isabs(name) and os.path.exists(name):
        return name
    d = getattr(config, "VISION_HAILO_DIR", None)
    if d:
        p = os.path.join(str(d), name)
        if os.path.exists(p):
            return p
    return ""


def _shared_vdevice():
    """Preferuj współdzielony VDevice z NpuEngine; w razie braku — własny (SHARED)."""
    from ..backends import npu as npumod
    engine = getattr(npumod, "NPU_ENGINE", None)
    if engine is not None:
        return engine.get_vdevice()
    from hailo_platform import VDevice, HailoSchedulingAlgorithm
    params = VDevice.create_params()
    params.scheduling_algorithm = HailoSchedulingAlgorithm.ROUND_ROBIN
    params.group_id = "SHARED"
    return VDevice(params)


def _npu_gate():
    """Współdzielona, priorytetowa kolejka NPU (Faza 4): detekcja nie wywłaszcza STT/czatu.

    Inferencja na NPU jest blokująca — kolejka porządkuje czekających (wizja = prio 2,
    STT = 0, czat = 1). W osobnym procesie (vision-api/watch, bez `ASTRO_NPU`) zwraca
    zwykły lock — tam detekcja i tak nie dzieli urządzenia z STT/VLM."""
    try:
        from ..backends import npu as npumod
        engine = getattr(npumod, "NPU_ENGINE", None)
        if engine is not None:
            return engine.gate(npumod.NpuGate.PRIO_VISION)
    except Exception:
        pass
    return _LOCAL_LOCK


def _letterbox(image, mh, mw):
    """Kwadratowy listbox z paddingiem (jak hailo-apps `default_preprocess`).

    Zwraca `(canvas, scale, xo, yo)` — do odwzorowania współrzędnych z powrotem na oryginał.
    """
    import cv2
    import numpy as np
    h, w = image.shape[:2]
    scale = min(mw / w, mh / h)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_CUBIC)
    canvas = np.full((mh, mw, 3), (114, 114, 114), dtype=np.uint8)
    xo, yo = (mw - nw) // 2, (mh - nh) // 2
    canvas[yo:yo + nh, xo:xo + nw] = resized
    return canvas, scale, xo, yo


class HailoDetector:
    """YOLOv8 na Hailo NPU. Ładowanie leniwe; jedno urządzenie dzielone z STT/VLM."""

    def __init__(self, hef=None):
        self.hef = hef or hef_path()
        self._model = None
        self._configured = None
        self._ctx = None
        self._in_name = ""
        self._out_name = ""
        self._in_shape = (640, 640, 3)
        self._out_shape = ()
        self._lock = threading.Lock()
        self._failed = False
        self._error = ""

    def available(self):
        return bool(self.hef) and os.path.exists(self.hef) and hailo_platform_available()

    def ready(self):
        return self._configured is not None

    def last_error(self):
        return self._error

    def _vdevice(self):
        return _shared_vdevice()

    def _ensure(self):
        if self._configured is not None:
            return self._configured
        if self._failed:
            raise RuntimeError(self._error)
        if not self.available():
            self._error = "brak HEF/hailo_platform dla detekcji NPU"
            self._failed = True
            raise RuntimeError(self._error)
        try:
            vd = self._vdevice()
            model = vd.create_infer_model(self.hef)
            model.set_batch_size(1)
            self._in_name = model.inputs[0].name
            self._in_shape = tuple(model.inputs[0].shape)
            out = model.outputs[0]
            self._out_name = out.name
            self._out_shape = tuple(out.shape)
            ctx = model.configure()
            configured = ctx.__enter__()
            self._model, self._configured, self._ctx = model, configured, ctx
            return configured
        except Exception as exc:  # trwała niedostępność (np. NPU trzyma inny proces)
            self._error = f"NPU detekcja niedostępna: {exc!r}"
            self._failed = True
            raise RuntimeError(self._error) from exc

    @staticmethod
    def _preprocess(image, in_shape):
        canvas, _scale, _xo, _yo = _letterbox(image, int(in_shape[0]), int(in_shape[1]))
        return canvas

    def detect_objects(self, image, prob=None):
        """Detekcja COCO na NPU. Zwraca [{label, score, box:[x1,y1,x2,y2]}] w skali obrazu."""
        import numpy as np
        prob = float(getattr(config, "VISION_NPU_SCORE", 0.45) if prob is None else prob)
        h, w = image.shape[:2]
        start = time.time()
        ok = True
        try:
            with self._lock, _npu_gate():
                configured = self._ensure()
                canvas = self._preprocess(image, self._in_shape)
                out_buffers = {self._out_name: np.empty(self._out_shape, dtype=np.float32)}
                bindings = configured.create_bindings(output_buffers=out_buffers)
                bindings.input().set_buffer(canvas)
                configured.run([bindings], timeout=10000)
                detections = bindings.output().get_buffer()
            if not isinstance(detections, list):
                raise RuntimeError("HEF bez NMS na urządzeniu — użyj modelu detekcyjnego z NMS")
            return self._decode(detections, h, w, prob)
        except Exception:
            ok = False
            raise
        finally:
            NPU_TELEMETRY.record("detect", time.time() - start, ok=ok,
                                 model=os.path.basename(self.hef) or "yolo")

    @staticmethod
    def _decode(detections, h, w, prob):
        """NMS-by-class → kontrakt CPU. detections: lista 80× (N,5) [ymin,xmin,ymax,xmax,score]."""
        from .engine import COCO_CLASSES
        size = max(h, w)
        pad = int(abs(h - w) / 2)
        out = []
        for cid, det in enumerate(detections):
            for row in det:
                score = float(row[4])
                if score < prob:
                    continue
                box = [float(v) * size for v in row[:4]]
                for i in range(4):
                    if i % 2 == 0:
                        if h != size:
                            box[i] -= pad
                    else:
                        if w != size:
                            box[i] -= pad
                xmin, ymin, xmax, ymax = box[1], box[0], box[3], box[2]
                label = COCO_CLASSES[cid] if cid < len(COCO_CLASSES) else f"class_{cid}"
                out.append({"label": label, "score": score,
                            "box": [max(0.0, xmin), max(0.0, ymin),
                                    min(float(w), xmax), min(float(h), ymax)]})
        out.sort(key=lambda o: -o["score"])
        return out

    def close(self):
        with self._lock:
            try:
                if self._ctx is not None:
                    self._ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._model = self._configured = self._ctx = None


class HailoFaceDetector:
    """SCRFD na Hailo NPU: ramki twarzy + 5 landmarków (do wyrównania pod SFace)."""

    def __init__(self, hef=None):
        self.hef = hef or face_hef_path()
        self._configured = None
        self._ctx = None
        self._in_shape = (640, 640, 3)
        self._out_names = []
        self._out_shapes = {}
        self._lock = threading.Lock()
        self._failed = False
        self._error = ""

    def available(self):
        return bool(self.hef) and os.path.exists(self.hef) and hailo_platform_available()

    def last_error(self):
        return self._error

    def _ensure(self):
        if self._configured is not None:
            return self._configured
        if self._failed:
            raise RuntimeError(self._error)
        if not self.available():
            self._error = "brak HEF/hailo_platform dla detekcji twarzy NPU"
            self._failed = True
            raise RuntimeError(self._error)
        try:
            from hailo_platform import FormatType
            vd = _shared_vdevice()
            model = vd.create_infer_model(self.hef)
            model.set_batch_size(1)
            self._in_shape = tuple(model.inputs[0].shape)
            for out in model.outputs:
                out.set_format_type(FormatType.FLOAT32)  # dequantyzacja na urządzeniu
            self._out_names = [o.name for o in model.outputs]
            self._out_shapes = {o.name: tuple(o.shape) for o in model.outputs}
            ctx = model.configure()
            configured = ctx.__enter__()
            self._configured, self._ctx = configured, ctx
            return configured
        except Exception as exc:
            self._error = f"NPU detekcja twarzy niedostępna: {exc!r}"
            self._failed = True
            raise RuntimeError(self._error) from exc

    def detect_faces(self, image, score=None):
        """Twarze na NPU. Kontrakt YuNet/CPU: {box:[x,y,w,h], score, landmarks:[10], raw:None}."""
        import numpy as np
        score = float(getattr(config, "VISION_FACE_SCORE", 0.5) if score is None else score)
        iou = float(getattr(config, "VISION_FACE_NMS", 0.4))
        h, w = image.shape[:2]
        start = time.time()
        ok = True
        try:
            with self._lock, _npu_gate():
                configured = self._ensure()
                canvas, scale, xo, yo = _letterbox(image, int(self._in_shape[0]),
                                                   int(self._in_shape[1]))
                out_buffers = {n: np.empty(self._out_shapes[n], dtype=np.float32)
                               for n in self._out_names}
                bindings = configured.create_bindings(output_buffers=out_buffers)
                bindings.input().set_buffer(canvas)
                configured.run([bindings], timeout=10000)
                res = {n: np.asarray(bindings.output(n).get_buffer(), dtype=np.float32)
                       for n in self._out_names}
            boxes, scores, landmarks = self._decode(res, score, iou)
            faces = []
            for box, sc, kps in zip(boxes, scores, landmarks):
                x1 = (box[0] - xo) / scale
                y1 = (box[1] - yo) / scale
                x2 = (box[2] - xo) / scale
                y2 = (box[3] - yo) / scale
                flat = [float((kps[k][0] - xo) / scale) for k in range(5)]
                yvals = [float((kps[k][1] - yo) / scale) for k in range(5)]
                inter = [v for pair in zip(flat, yvals) for v in pair]
                faces.append({"box": [x1, y1, x2 - x1, y2 - y1], "score": float(sc),
                              "landmarks": inter, "raw": None})
            faces.sort(key=lambda f: -f["score"])
            return faces
        except Exception:
            ok = False
            raise
        finally:
            NPU_TELEMETRY.record("faces", time.time() - start, ok=ok,
                                 model=os.path.basename(self.hef) or "scrfd")

    @staticmethod
    def _decode(res, score_th=0.5, iou_th=0.4):
        """SCRFD → (boxes, scores, landmarks) w przestrzeni listboxa (px). Jak hailo-apps scrfd.cpp."""
        import numpy as np
        scales = {}
        for arr in res.values():
            if arr.ndim != 3:
                continue
            fm = int(arr.shape[0])
            d = scales.setdefault(fm, {})
            if arr.shape[-1] == 2:
                d["score"] = arr
            elif arr.shape[-1] == 8:
                d["box"] = arr
            elif arr.shape[-1] == 20:
                d["kps"] = arr
        boxes, scores, landmarks = [], [], []
        for fm, d in sorted(scales.items()):
            if not all(k in d for k in ("score", "box", "kps")):
                continue
            stride = 640 // fm
            if stride * fm != 640:
                continue
            sc = d["score"].reshape(-1)          # kotwice: 2 na komórkę (interleave)
            bx = d["box"].reshape(-1, 4)
            kp = d["kps"].reshape(-1, 10)
            xs = np.arange(fm) * stride
            gx, gy = np.meshgrid(xs, xs)
            centers = np.repeat(np.stack([gx.ravel(), gy.ravel()], axis=1), 2, axis=0)
            for i in np.nonzero(sc >= score_th)[0]:
                cx, cy = centers[i]
                x1 = cx - bx[i, 0] * stride
                y1 = cy - bx[i, 1] * stride
                x2 = cx + bx[i, 2] * stride
                y2 = cy + bx[i, 3] * stride
                lm = centers[i].reshape(1, 2).repeat(5, axis=0) + kp[i].reshape(5, 2) * stride
                boxes.append([float(x1), float(y1), float(x2), float(y2)])
                scores.append(float(sc[i]))
                landmarks.append(lm.tolist())
        keep = HailoFaceDetector._nms(boxes, scores, iou_th)
        return ([boxes[i] for i in keep], [scores[i] for i in keep],
                [landmarks[i] for i in keep])

    @staticmethod
    def _nms(boxes, scores, iou_th):
        import numpy as np
        if not boxes:
            return []
        b = np.asarray(boxes, dtype=np.float64)
        s = np.asarray(scores, dtype=np.float64)
        order = np.argsort(-s)
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            if order.size == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(b[i, 0], b[rest, 0])
            yy1 = np.maximum(b[i, 1], b[rest, 1])
            xx2 = np.minimum(b[i, 2], b[rest, 2])
            yy2 = np.minimum(b[i, 3], b[rest, 3])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            area_i = (b[i, 2] - b[i, 0]) * (b[i, 3] - b[i, 1])
            area_r = (b[rest, 2] - b[rest, 0]) * (b[rest, 3] - b[rest, 1])
            iou = inter / (area_i + area_r - inter + 1e-9)
            order = rest[iou < iou_th]
        return keep

    def close(self):
        with self._lock:
            try:
                if self._ctx is not None:
                    self._ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._configured = self._ctx = None


def get_detector():
    """Singleton detektora NPU (albo None, gdy wyłączony lub to nie proces-właściciel NPU).

    NPU (Hailo-10H) ma urządzenie na wyłączność procesu — detekcję na NPU uruchamiamy tylko
    tam, gdzie działa genai (astro.service: `ASTRO_NPU=1`). Inne procesy (vision-api/watch)
    nie próbują otwierać VDevice (unikamy głośnych błędów HailoRT) — liczą na CPU.
    """
    global _DETECTOR
    if not getattr(config, "VISION_NPU", False):
        return None
    if not getattr(config, "NPU_ENABLED", False):
        return None
    with _LOCK:
        if _DETECTOR is None:
            _DETECTOR = HailoDetector()
        return _DETECTOR


def get_face_detector():
    """Singleton detektora twarzy NPU (SCRFD) — te same zasady co `get_detector()`."""
    global _FACE_DETECTOR
    if not getattr(config, "VISION_NPU", False):
        return None
    if not getattr(config, "NPU_ENABLED", False):
        return None
    with _LOCK:
        if _FACE_DETECTOR is None:
            _FACE_DETECTOR = HailoFaceDetector()
        return _FACE_DETECTOR


def reset():
    """Zwalnia singletony (testy / restart urządzenia)."""
    global _DETECTOR, _FACE_DETECTOR
    with _LOCK:
        if _DETECTOR is not None:
            _DETECTOR.close()
        if _FACE_DETECTOR is not None:
            _FACE_DETECTOR.close()
        _DETECTOR = None
        _FACE_DETECTOR = None
