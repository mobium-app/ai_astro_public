"""Silnik wizji AI ASTRO (lokalny, ONNX/OpenCV): twarze, osoby, przedmioty, emocje, wiek/płeć.

Modele (`models/vision/`):
  * `face_detection_yunet_2023mar.onnx`       — detekcja twarzy (+5 landmarków),
  * `face_recognition_sface_2021dec.onnx`     — embedding twarzy (128-d, rozpoznawanie osób),
  * `object_detection_nanodet_2022nov.onnx`   — detekcja obiektów COCO (osoby, przedmioty),
  * `facial_expression_recognition_mobilefacenet_2022july.onnx` — 7 emocji,
  * `age_googlenet.onnx` + `gender_googlenet.onnx` — wiek/płeć (Levi & Hassner, Adience).
Wszystko na CPU (osobne, leniwe ładowanie; brak chmury). Gdy brak modelu — czytelny komunikat.
"""

from __future__ import annotations

import os
import threading

from .. import config

_LOCK = threading.Lock()
_MODELS = {}

FACE_MODEL = "face_detection_yunet_2023mar.onnx"
FACE_EMBED_MODEL = "face_recognition_sface_2021dec.onnx"
OBJECT_MODEL = "object_detection_nanodet_2022nov.onnx"
EXPRESSION_MODEL = "facial_expression_recognition_mobilefacenet_2022july.onnx"
REID_MODEL = "person_reid_youtu_2021nov.onnx"
AGE_MODEL = "age_googlenet.onnx"
GENDER_MODEL = "gender_googlenet.onnx"

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush")

EXPRESSIONS = ("angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised")
EXPRESSIONS_PL = {"angry": "zły", "disgust": "obrzydzenie", "fearful": "przestraszony",
                  "happy": "wesoły", "neutral": "neutralny", "sad": "smutny",
                  "surprised": "zaskoczony"}

# Wiek (GoogleNet, Adience — 8 klas Levi & Hassner) i płeć (klasa 0 = kobieta, 1 = mężczyzna).
AGE_RANGES = ("0-2", "4-6", "8-12", "15-20", "25-32", "38-43", "48-53", "60-100")
AGE_RANGES_PL = {"0-2": "od 0 do 2 lat", "4-6": "od 4 do 6 lat", "8-12": "od 8 do 12 lat",
                 "15-20": "od 15 do 20 lat", "25-32": "od 25 do 32 lat",
                 "38-43": "od 38 do 43 lat", "48-53": "od 48 do 53 lat",
                 "60-100": "powyżej 60 lat"}
GENDERS = ("kobieta", "mężczyzna")
# Średnie dla wejścia 224×224 BGR (model Adience, jak w oryginale Levi & Hassner).
AGEGENDER_MEAN = (104.0, 117.0, 123.0)


def model_path(name):
    return os.path.join(str(getattr(config, "VISION_MODELS_DIR", "")), name)


def available(kind="all"):
    try:
        from . import hailo
        if kind in ("objects", "all"):
            det = hailo.get_detector()
            if det is not None and det.available():
                return True
        if kind == "face":
            fdet = hailo.get_face_detector()
            if fdet is not None and fdet.available():
                return True
    except Exception:
        pass
    files = {"face": [FACE_MODEL], "recognize": [FACE_MODEL, FACE_EMBED_MODEL],
             "objects": [OBJECT_MODEL], "expression": [FACE_MODEL, FACE_EMBED_MODEL,
                                                       EXPRESSION_MODEL],
             "agegender": [FACE_MODEL, FACE_EMBED_MODEL, AGE_MODEL, GENDER_MODEL],
             "bodies": [OBJECT_MODEL, REID_MODEL], "reid": [OBJECT_MODEL, REID_MODEL]}.get(
                 kind, [])
    if kind == "all":
        files = [FACE_MODEL, FACE_EMBED_MODEL, OBJECT_MODEL, EXPRESSION_MODEL, REID_MODEL,
                 AGE_MODEL, GENDER_MODEL]
    return all(os.path.isfile(model_path(f)) for f in files)


def _load(key, loader):
    with _LOCK:
        if key not in _MODELS:
            _MODELS[key] = loader()
        return _MODELS[key]


def _yunet():
    import cv2

    def loader():
        return cv2.FaceDetectorYN.create(model_path(FACE_MODEL), "", (320, 320),
                                         0.6, 0.3, 5000)
    return _load("yunet", loader)


def _sface():
    import cv2

    def loader():
        return cv2.FaceRecognizerSF.create(model_path(FACE_EMBED_MODEL), "")
    return _load("sface", loader)


def _nanodet():
    import cv2

    def loader():
        net = cv2.dnn.readNet(model_path(OBJECT_MODEL))
        return net
    return _load("nanodet", loader)


def _fer():
    import cv2

    def loader():
        return cv2.dnn.readNet(model_path(EXPRESSION_MODEL))
    return _load("fer", loader)


def _reid():
    import onnxruntime as ort

    def loader():
        return ort.InferenceSession(model_path(REID_MODEL),
                                    providers=["CPUExecutionProvider"])
    return _load("reid", loader)


def _agegen():
    import cv2

    def loader():
        return (cv2.dnn.readNetFromONNX(model_path(AGE_MODEL)),
                cv2.dnn.readNetFromONNX(model_path(GENDER_MODEL)))
    return _load("agegen", loader)


def age_gender(image, face):
    """Wiek i płeć dla twarzy (Levi & Hassner, GoogleNet, Adience) albo None.

    Wyrównaną twarz 112×112 (jak dla SFace) skalujemy do 224×224 BGR i odejmujemy średnie
    modelu (104, 117, 123). Zwraca {"age": "25-32", "gender": "kobieta", "age_score": ..,
    "gender_score": ..} — etykiety jak w `AGE_RANGES`/`GENDERS`.
    """
    import cv2
    import numpy as np
    rec = _sface()
    aligned = _aligned_face(image, face, rec)
    if aligned is None:
        return None
    blob = cv2.dnn.blobFromImage(aligned, 1.0, (224, 224), AGEGENDER_MEAN, False, False)
    age_net, gender_net = _agegen()
    age_net.setInput(blob)
    age_out = np.asarray(age_net.forward()).reshape(-1)
    gender_net.setInput(blob)
    gender_out = np.asarray(gender_net.forward()).reshape(-1)
    if age_out.size == 0 or gender_out.size == 0:
        return None
    return {"age": AGE_RANGES[int(np.argmax(age_out))],
            "gender": GENDERS[int(np.argmax(gender_out))],
            "age_score": round(float(np.max(age_out)), 3),
            "gender_score": round(float(np.max(gender_out)), 3)}


def person_boxes(image, prob=0.45):
    """Ramki osób z detektora obiektów (COCO 'person')."""
    return [o["box"] for o in detect_objects(image, prob) if o["label"] == "person"]


def person_embedding(image, box):
    """Znormalizowany embedding sylwetki (YouTuReID, 768-d) dla ramki osoby, albo None.

    Działa, gdy twarzy nie widać (osoba odwrócona/oddalona) — uzupełnia rozpoznawanie twarzy.
    """
    import cv2
    import numpy as np
    x1, y1, x2, y2 = [int(v) for v in box]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
    if x2 - x1 < 12 or y2 - y1 < 24:
        return None
    crop = image[y1:y2, x1:x2]
    crop = cv2.resize(crop, (128, 256), interpolation=cv2.INTER_LINEAR)
    rgb = crop[:, :, ::-1].astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    rgb = (rgb - mean) / std
    blob = np.transpose(rgb, (2, 0, 1))[np.newaxis].astype(np.float32)
    sess = _reid()
    out = sess.run(None, {sess.get_inputs()[0].name: blob})[0]
    vec = np.asarray(out).reshape(-1)
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm else vec.tolist()


def detect_faces(image, score=None):
    """Detekcja twarzy: najpierw Hailo NPU (SCRFD), z fallbackiem na CPU (YuNet).

    Kontrakt identyczny: [{box:[x,y,w,h], score, landmarks:[10], raw}]. NPU zwraca `raw=None`
    (bez wiersza YuNet) — wyrównanie pod SFace robi `_align_landmarks` z 5 landmarków.
    """
    detector = _npu_face_detector()
    if detector is not None:
        try:
            if detector.available():
                return detector.detect_faces(image, score)
        except Exception:
            pass
    return _detect_faces_cpu(image, 0.6 if score is None else score)


def _npu_face_detector():
    if not getattr(config, "VISION_NPU", False):
        return None
    try:
        from . import hailo
        return hailo.get_face_detector()
    except Exception:
        return None


def _detect_faces_cpu(image, score=0.6):
    """Zwraca listę twarzy: {box:[x,y,w,h], score, landmarks:[...], raw: np.ndarray(15)}."""
    import cv2
    h, w = image.shape[:2]
    det = _yunet()
    det.setInputSize((w, h))
    _ok, faces = det.detect(image)
    out = []
    if faces is None:
        return out
    for f in faces:
        if float(f[-1]) < score:
            continue
        out.append({"box": [float(x) for x in f[:4]], "score": float(f[-1]),
                    "landmarks": [float(x) for x in f[4:14]], "raw": f})
    return out


# Referencyjne punkty twarzy 112×112 (standard ArcFace/SFace, jak `FaceRecognizerSF::alignCrop`).
_SFACE_REF = ((38.2946, 51.6963), (73.5318, 51.5014), (56.0252, 71.7366),
              (41.5493, 92.3655), (70.7299, 92.2041))


def _align_landmarks(image, landmarks):
    """Wyrównuje twarz do 112×112 na podstawie 5 landmarków (gdy brak `raw` z YuNet)."""
    import cv2
    import numpy as np
    if not landmarks or len(landmarks) < 10:
        return None
    pts = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
    ref = np.asarray(_SFACE_REF, dtype=np.float32)
    matrix, _ = cv2.estimateAffinePartial2D(pts, ref, method=cv2.LMEDS)
    if matrix is None:
        return None
    return cv2.warpAffine(image, matrix, (112, 112), borderValue=0)


def _aligned_face(image, face, recognizer):
    """Wyrównana twarz: `raw` (YuNet) → alignCrop; same landmarki (NPU SCRFD) → własna transformacja."""
    raw = face.get("raw") if face else None
    if raw is not None:
        return recognizer.alignCrop(image, raw)
    return _align_landmarks(image, face.get("landmarks") if face else None)


def face_embedding(image, face):
    """Znormalizowany embedding SFace (lista float) albo None."""
    import numpy as np
    rec = _sface()
    aligned = _aligned_face(image, face, rec)
    if aligned is None:
        return None
    feat = np.asarray(rec.feature(aligned)).reshape(-1)
    norm = float(np.linalg.norm(feat))
    return (feat / norm).tolist() if norm else feat.tolist()


def expression(image, face):
    """Jedna z EXPRESSIONS dla twarzy (albo "")."""
    import cv2
    import numpy as np
    rec = _sface()
    aligned = _aligned_face(image, face, rec)
    if aligned is None:
        return ""
    img = cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = (img - 0.5) / 0.5
    blob = cv2.dnn.blobFromImage(img)
    net = _fer()
    net.setInput(blob, "data")
    out = net.forward(["label"])
    return EXPRESSIONS[int(np.argmax(out[0], axis=1)[0])]


def _letterbox(image, size=(416, 416)):
    import cv2
    h, w = image.shape[:2]
    if h == w:
        return cv2.resize(image, size, interpolation=cv2.INTER_AREA), (0, 0, size[0], size[1])
    if h > w:
        newh, neww = size[0], max(1, int(size[1] * w / h))
        img = cv2.resize(image, (neww, newh), interpolation=cv2.INTER_AREA)
        left = (size[1] - neww) // 2
        img = cv2.copyMakeBorder(img, 0, 0, left, size[1] - neww - left, cv2.BORDER_CONSTANT)
        return img, (0, left, newh, neww)
    newh, neww = max(1, int(size[0] * h / w)), size[1]
    img = cv2.resize(image, (neww, newh), interpolation=cv2.INTER_AREA)
    top = (size[0] - newh) // 2
    img = cv2.copyMakeBorder(img, top, size[0] - newh - top, 0, 0, cv2.BORDER_CONSTANT)
    return img, (top, 0, newh, neww)


def detect_objects(image, prob=0.45):
    """Detekcja COCO: najpierw Hailo NPU (YOLOv8), z fallbackiem na CPU (NanoDet).

    Kontrakt identyczny dla obu torów: [{label, score, box:[x1,y1,x2,y2]}] w oryginalnej skali.
    NPU wyłączony niedostępny/zajęty → cicho liczymy na CPU (bez przerywania działania).
    """
    detector = _npu_detector()
    if detector is not None:
        try:
            if detector.available():
                return detector.detect_objects(image, prob)
        except Exception:
            pass
    return _detect_objects_cpu(image, prob)


def _npu_detector():
    if not getattr(config, "VISION_NPU", False):
        return None
    try:
        from . import hailo
        return hailo.get_detector()
    except Exception:
        return None


def _detect_objects_cpu(image, prob=0.45):
    """Detekcja COCO (NanoDet). Zwraca [{label, score, box:[x1,y1,x2,y2]}] w oryginalnej skali."""
    import cv2
    import numpy as np
    letterboxed, (top, left, newh, neww) = _letterbox(image)
    img = letterboxed.astype(np.float32)
    mean = np.array([103.53, 116.28, 123.675], dtype=np.float32)
    std = np.array([57.375, 57.12, 58.395], dtype=np.float32)
    img = (img - mean) / std
    blob = cv2.dnn.blobFromImage(img)
    net = _nanodet()
    net.setInput(blob)
    outs = [np.asarray(o) for o in net.forward(net.getUnconnectedOutLayersNames())]
    # Wyjścia: pierwsza połowa = klasy (per poziom), druga = boxy (te same poziomy).
    levels = len(outs) // 2
    cls_outs, box_outs = outs[:levels], outs[levels:]
    h, w = image.shape[:2]
    ratio_h = h / newh if newh else 1.0
    ratio_w = w / neww if neww else 1.0
    boxes, scores, class_ids = [], [], []
    proj = np.arange(8)
    for cls_score, bbox_pred in zip(cls_outs, box_outs):
        cls_score = cls_score.reshape(-1, cls_score.shape[-1])
        bbox_pred = bbox_pred.reshape(-1, bbox_pred.shape[-1])
        points = cls_score.shape[0]
        feat = int(round(points ** 0.5))
        stride = int(round(416 / feat)) if feat else 1
        shift = np.arange(feat) * stride
        xv, yv = np.meshgrid(shift, shift)
        anchors = np.column_stack((xv.flatten() + 0.5 * (stride - 1),
                                   yv.flatten() + 0.5 * (stride - 1)))
        x_exp = np.exp(bbox_pred.reshape(-1, 8))
        dist = (x_exp / x_exp.sum(axis=1, keepdims=True)) @ proj
        dist = dist.reshape(-1, 4) * stride
        x1 = np.clip(anchors[:, 0] - dist[:, 0], 0, 416)
        y1 = np.clip(anchors[:, 1] - dist[:, 1], 0, 416)
        x2 = np.clip(anchors[:, 0] + dist[:, 2], 0, 416)
        y2 = np.clip(anchors[:, 1] + dist[:, 3], 0, 416)
        cid = np.argmax(cls_score, axis=1)
        conf = np.max(cls_score, axis=1)
        keep = conf >= prob
        for i in np.nonzero(keep)[0]:
            boxes.append([float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i])])
            scores.append(float(conf[i]))
            class_ids.append(int(cid[i]))
    out = []
    if boxes:
        idx = cv2.dnn.NMSBoxes([[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b in boxes],
                               scores, prob, 0.6)
        for i in np.array(idx).reshape(-1):
            b = boxes[i]
            x1 = max(0.0, (b[0] - left) * ratio_w)
            y1 = max(0.0, (b[1] - top) * ratio_h)
            x2 = min(float(w), (b[2] - left) * ratio_w)
            y2 = min(float(h), (b[3] - top) * ratio_h)
            out.append({"label": COCO_CLASSES[class_ids[i]], "score": scores[i],
                        "box": [x1, y1, x2, y2]})
    return out
